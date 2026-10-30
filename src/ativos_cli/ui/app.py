"""Aplicação de tela cheia: busca no topo, carteira ou resultados abaixo (prompt_toolkit + Rich).

Com o campo de busca vazio, a lista mostra a carteira; ao digitar, mostra os resultados.

A interface nunca acessa o site nem o banco diretamente. Toda operação demorada
(atualizar, consultar, adicionar, remover) entra numa fila e roda numa thread de
trabalho, uma de cada vez; a tela só lê o estado já calculado.
"""

import logging
import queue
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import (
    ANSI,
    StyleAndTextTuples,
    split_lines,
    to_formatted_text,
)
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings.basic import load_basic_bindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import (
    BeforeInput,
    Processor,
    Transformation,
    TransformationInput,
)
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame
from rich.console import Console, Group, RenderableType
from rich.text import Text

from ativos_cli import config
from ativos_cli.errors import AtivosError
from ativos_cli.models import AssetView, CatalogEntry, DisplayStatus, FetchResult, FetchStatus
from ativos_cli.services.asset_service import AssetService
from ativos_cli.services.search_service import SearchHit, SearchService, rank
from ativos_cli.ui.tables import ADD_BUTTON, assets_table, details_panel, search_table
from ativos_cli.ui.theme import render_ansi

log = logging.getLogger(__name__)

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# Espera a digitação parar antes de consultar a data-com dos resultados no site.
QUOTE_DELAY_SECONDS = 0.4
PLACEHOLDER = "Buscar fundo por nome ou ticker..."

STYLE = Style.from_dict(
    {
        "frame.border": "#6c6c6c",
        "frame.label": "bold",
        "rule": "#6c6c6c",
        "title": "bold",
        # Não usar "search": é uma classe padrão do prompt_toolkit com fundo amarelo.
        "searchbox": "",
        "searchbox.icon": "ansicyan",
        "placeholder": "#808080 italic",
        "footer.key": "ansicyan bold",
        "footer": "#a0a0a0",
        "status.ok": "ansigreen",
        "status.warn": "ansiyellow",
        "status.fail": "ansired",
        "status.info": "#a0a0a0",
        "status.busy": "ansicyan",
    }
)


class Mode(StrEnum):
    LIST = "list"
    DETAILS = "details"
    CONFIRM = "confirm"


@dataclass
class Confirmation:
    question: str
    on_yes: Callable[[], None]


MouseHandler = Callable[[MouseEvent], object]
Span = tuple[int, int, MouseHandler]
TICKER_IN_LINE = re.compile(r"\b([A-Z]{4}\d{2}B?)\b")


def clickable(
    fragments: StyleAndTextTuples, spans_for_line: Callable[[str], list[Span]]
) -> StyleAndTextTuples:
    """Liga handlers de mouse a trechos de cada linha de um texto já renderizado.

    `spans_for_line(texto)` devolve (início, fim, handler) por linha; em trechos
    sobrepostos vale o último (ex.: botão dentro da linha clicável).
    """
    out: StyleAndTextTuples = []
    for number, line in enumerate(split_lines(fragments)):
        if number:
            out.append(("", "\n"))
        spans = spans_for_line("".join(f[1] for f in line))
        if not spans:
            out.extend(line)
            continue
        pos = 0
        for style, text, *_ in line:
            bounds = {b - pos for s, e, _ in spans for b in (s, e) if pos < b < pos + len(text)}
            cuts = sorted({0, len(text)} | bounds)
            for a, b in pairwise(cuts):
                handler = None
                for s, e, h in spans:
                    if s <= pos + a < e:
                        handler = h
                piece = text[a:b]
                out.append((style, piece, handler) if handler else (style, piece))
            pos += len(text)
    return out


class Placeholder(Processor):
    """Texto de dica exibido enquanto o campo está vazio."""

    def __init__(self, text: str) -> None:
        self.text = text

    def apply_transformation(self, ti: TransformationInput) -> Transformation:
        if ti.document.text == "" and ti.lineno == 0:
            return Transformation([*ti.fragments, ("class:placeholder", self.text)])
        return Transformation(ti.fragments)


class AtivosApp:
    def __init__(
        self,
        service: AssetService,
        search: SearchService,
        console: Console,
        term: str = "",
    ) -> None:
        self.service = service
        self.search = search
        self.console = console

        self.mode = Mode.LIST
        self.wallet: list[AssetView] = []
        self.wallet_loaded = False
        self.updated: set[str] = set()
        self.refresh_label = ""
        self.wallet_sel = 0
        self.catalog: list[CatalogEntry] = []
        self.catalog_requested = False
        self.hits: list[SearchHit] = []
        self.search_sel = 0
        self.details: AssetView | None = None
        self.confirmation: Confirmation | None = None
        self.mode_before_confirm = Mode.LIST
        self.message: tuple[str, str] | None = None
        self.busy: str | None = None
        self.tick = 0

        self.jobs: queue.Queue = queue.Queue()
        self.worker = threading.Thread(target=self._work, daemon=True)

        self.search_views: dict[str, AssetView] = {}
        self.quotes_pending: set[str] = set()
        self.quotes_fetched: set[str] = set()
        self.quote_delay = QUOTE_DELAY_SECONDS
        self.quote_generation = 0
        self.quote_timer: threading.Timer | None = None

        self.search_buffer = Buffer(multiline=False, on_text_changed=lambda _: self._rerank())
        self.search_buffer.text = term
        self.app = self._build_app()

    # --- ciclo de vida ---------------------------------------------------------

    def run(self) -> None:
        self.worker.start()
        self.submit("Carregando", self._load_initial)
        try:
            self.app.run()
        finally:
            self.jobs.put(None)

    def _load_initial(self) -> None:
        self.catalog = self.search.repo.list_catalog()
        self.wallet = self._wallet_views()
        self.wallet_loaded = True
        self._rerank()
        if self.searching:
            # Busca vinda da linha de comando: a data-com dos resultados vem antes de tudo.
            self._quotes_job(self.quote_generation)
        # A lista de fundos vem antes da atualização da carteira: a busca fica pronta logo.
        self._ensure_catalog()
        if self.wallet:
            self.submit("Atualizando carteira", self._refresh_job)

    # --- fila de trabalho ------------------------------------------------------

    def submit(self, label: str, fn: Callable[[], Any]) -> None:
        self.jobs.put((label, fn))

    def _work(self) -> None:
        while (job := self.jobs.get()) is not None:
            label, fn = job
            self.busy = label
            self._invalidate()
            try:
                fn()
            except AtivosError as exc:
                self.flash(str(exc), "fail")
            except Exception as exc:
                log.exception("Erro inesperado")
                self.flash(f"Erro inesperado: {exc}", "fail")
            finally:
                self.busy = None
                self._invalidate()

    def _invalidate(self) -> None:
        # O texto inicial da busca dispara _rerank antes de o app existir.
        app = getattr(self, "app", None)
        if app is not None and app.is_running:
            app.invalidate()

    def flash(self, text: str, kind: str = "info") -> None:
        self.message = (kind, text)
        self._invalidate()

    # --- operações (rodam na thread de trabalho) -------------------------------

    def _wallet_views(self) -> list[AssetView]:
        tickers = self.service.repo.wallet_tickers()
        return [self.service.view(t, updated_now=t in self.updated) for t in tickers]

    def _refresh_job(self, tickers: list[str] | None = None) -> None:
        targets = tickers or self.service.repo.wallet_tickers()
        done = {"n": 0}

        def progress(result: FetchResult) -> None:
            done["n"] += 1
            self.busy = f"Atualizando {done['n']}/{len(targets)} · {result.ticker}"
            self._invalidate()

        summary = self.service.refresh(targets, on_progress=progress)
        for view in summary.views:
            if view.status == DisplayStatus.UPDATED:
                self.updated.add(view.ticker)
            else:
                self.updated.discard(view.ticker)
        self.wallet = self._wallet_views()
        failed = len(summary.failed)
        if tickers is None:
            self.refresh_label = "concluída" if not failed else f"{failed} com falha"
        if self.details and self.details.ticker in {v.ticker for v in summary.views}:
            self.details = self.service.view(
                self.details.ticker, self.details.ticker in self.updated
            )
        if failed:
            self.flash(f"{failed} ativo(s) não foram atualizados; exibindo o cache.", "warn")
        else:
            self.flash("Dados atualizados.", "ok")

    def _ensure_catalog(self) -> None:
        """Baixa a lista de ativos uma vez por sessão; em falha, usa a lista salva."""
        if self.catalog_requested:
            return
        self.catalog_requested = True

        def job() -> None:
            try:
                self.search.update_catalog()
            except AtivosError as exc:
                if not self.search.repo.list_catalog():
                    raise
                self.flash(f"{exc} Usando a lista salva.", "warn")
            self.catalog = self.search.repo.list_catalog()
            self._rerank()

        self.submit("Atualizando lista de ativos", job)

    def _rerank(self) -> None:
        # Antes da carga inicial (texto vindo da linha de comando), quem baixa a lista é ela.
        if self.searching and self.wallet_loaded:
            self._ensure_catalog()
        self.hits = rank(self.search_buffer.text, self.catalog, limit=50)
        self.search_sel = 0
        self._schedule_quotes()
        self._invalidate()

    def _schedule_quotes(self) -> None:
        """Agenda a consulta da data-com dos primeiros resultados quando a digitação para."""
        self.quote_generation += 1
        generation = self.quote_generation
        if self.quote_timer:
            self.quote_timer.cancel()
        if not self.hits:
            return

        def submit() -> None:
            self.submit("Consultando datas-com", lambda: self._quotes_job(generation))

        if self.quote_delay <= 0:
            submit()
            return
        self.quote_timer = threading.Timer(self.quote_delay, submit)
        self.quote_timer.daemon = True
        self.quote_timer.start()

    def _quotes_job(self, generation: int) -> None:
        """Mostra o último dado salvo na hora e consulta no site os que não estão recentes."""
        if generation != self.quote_generation:
            return  # o termo mudou; outra consulta já foi agendada
        top = [h.entry.ticker for h in self.hits[: config.SEARCH_LIMIT]]
        for ticker in top:
            if ticker not in self.search_views:
                self.search_views[ticker] = self.service.view(ticker)
        targets = [
            t
            for t in top
            if t not in self.quotes_fetched
            and not self.service.is_fresh(t, config.SEARCH_FRESH_FOR)
        ]
        if not targets:
            return
        self.quotes_pending.update(targets)
        self._invalidate()

        def on_result(result: FetchResult) -> None:
            # Mostra cada data-com assim que chega, sem esperar os demais.
            ok = result.status == FetchStatus.OK
            self.search_views[result.ticker] = self.service.view(result.ticker, updated_now=ok)
            self.quotes_pending.discard(result.ticker)
            self._invalidate()

        try:
            summary = self.service.refresh(targets, on_progress=on_result)
        finally:
            self.quotes_pending.difference_update(targets)
        for view in summary.views:
            self.search_views[view.ticker] = view
            self.quotes_fetched.add(view.ticker)
            if view.status == DisplayStatus.UPDATED:
                self.updated.add(view.ticker)
        if any(v.in_wallet for v in summary.views):
            self.wallet = self._wallet_views()

    # --- ações da interface ------------------------------------------------------

    @property
    def searching(self) -> bool:
        """Há texto na busca: a lista mostra resultados em vez da carteira."""
        return bool(self.search_buffer.text.strip())

    @property
    def selection(self) -> int:
        return self.search_sel if self.searching else self.wallet_sel

    def move(self, delta: int) -> None:
        if self.searching:
            if self.hits:
                self.search_sel = max(0, min(len(self.hits) - 1, self.search_sel + delta))
        elif self.wallet:
            self.wallet_sel = max(0, min(len(self.wallet) - 1, self.wallet_sel + delta))

    def clear_search(self) -> None:
        self.search_buffer.text = ""

    def open_details(self) -> None:
        if not self.searching:
            if not self.wallet:
                return
            self.details = self.wallet[self.wallet_sel]
            self.mode = Mode.DETAILS
            return
        if not self.hits:
            return
        ticker = self.hits[self.search_sel].entry.ticker

        def job() -> None:
            view = self.service.lookup(ticker)
            if view.status == DisplayStatus.UPDATED:
                self.updated.add(ticker)
                self.wallet = self._wallet_views()
            self.details = view
            self.mode = Mode.DETAILS

        self.submit(f"Consultando {ticker}", job)

    def close_details(self) -> None:
        self.mode = Mode.LIST
        self.details = None
        self._focus()

    def _focus(self) -> None:
        """Campo de busca na lista; corpo da tela nos detalhes (letras viram atalhos)."""
        if self.mode == Mode.LIST:
            self.app.layout.focus(self.search_buffer)
        else:
            self.app.layout.focus(self.body_window)

    def add_current(self) -> None:
        view = self.details
        if view is None or view.in_wallet:
            return
        self.add_ticker(view.ticker)

    def add_ticker(self, ticker: str) -> None:
        if ticker in {v.ticker for v in self.wallet}:
            return

        def job() -> None:
            outcome = self.service.add(ticker)
            self.wallet = self._wallet_views()
            if self.details and self.details.ticker == ticker:
                self.details = outcome.view
            if outcome.warning:
                self.flash(outcome.warning, "warn")
            else:
                self.flash(f"{ticker} adicionado à carteira.", "ok")

        self.submit(f"Adicionando {ticker}", job)

    def ask_remove(self) -> None:
        if self.mode == Mode.DETAILS and self.details:
            ticker = self.details.ticker
        elif not self.searching and self.wallet:
            ticker = self.wallet[self.wallet_sel].ticker
        else:
            return
        if ticker not in {v.ticker for v in self.wallet}:
            return
        question = f"Remover {ticker} da carteira? O histórico de consultas será mantido."

        def remove() -> None:
            def job() -> None:
                self.service.remove(ticker)
                self.updated.discard(ticker)
                self.wallet = self._wallet_views()
                self.wallet_sel = max(0, min(self.wallet_sel, len(self.wallet) - 1))
                if self.details and self.details.ticker == ticker:
                    self.details = self.service.view(ticker)
                self.flash(f"{ticker} removido da carteira.", "ok")

            self.submit(f"Removendo {ticker}", job)

        self.confirmation = Confirmation(question, remove)
        self.mode_before_confirm = self.mode
        self.mode = Mode.CONFIRM

    def answer(self, yes: bool) -> None:
        confirmation = self.confirmation
        self.confirmation = None
        self.mode = self.mode_before_confirm
        if yes and confirmation:
            confirmation.on_yes()

    def refresh(self) -> None:
        if self.mode == Mode.DETAILS and self.details:
            ticker = self.details.ticker
            self.submit(f"Atualizando {ticker}", lambda: self._refresh_job([ticker]))
        elif self.wallet:
            self.submit("Atualizando carteira", self._refresh_job)

    # --- renderização ------------------------------------------------------------

    def _width(self) -> int:
        return max(40, self.app.output.get_size().columns - 4)

    def _height(self) -> int:
        chrome = 8 if self.mode != Mode.DETAILS else 5
        return max(5, self.app.output.get_size().rows - chrome)

    def _rich(self, renderable: RenderableType) -> ANSI:
        return ANSI(render_ansi(self.console, renderable, self._width()))

    def _heading(self) -> StyleAndTextTuples:
        """Linha acima da lista: o que está sendo exibido."""
        if self.mode == Mode.DETAILS and self.details:
            return [("class:title", f" {self.details.ticker}")]
        if self.searching:
            out: StyleAndTextTuples = [("class:title", " Resultados")]
            if self.hits:
                out.append(("class:status.info", f" · {len(self.hits)} encontrados"))
            return out
        out = [("class:title", " Minha carteira")]
        if self.wallet_loaded:
            out.append(("class:status.info", f" · Ativos: {len(self.wallet)}"))
            if self.refresh_label:
                out.append(("class:status.info", f" · Atualização: {self.refresh_label}"))
        return out

    def _visible(self, count: int, selected: int, rows: int) -> tuple[int, int]:
        """Janela de linhas visíveis que mantém a seleção na tela."""
        if count <= rows:
            return 0, count
        start = min(max(0, selected - rows // 2), count - rows)
        return start, start + rows

    def _body(self) -> StyleAndTextTuples:
        if self.mode == Mode.DETAILS and self.details:
            return to_formatted_text(self._rich(details_panel(self.details, self._width(), True)))
        if self.searching:
            return self._search_fragments()
        return to_formatted_text(self._rich(self._wallet_body()))

    def _search_fragments(self) -> StyleAndTextTuples:
        """Resultados com mouse: clicar seleciona a linha (de novo, abre) e o botão adiciona."""
        rows = {h.entry.ticker: i for i, h in enumerate(self.hits)}

        def spans(line: str) -> list[Span]:
            match = TICKER_IN_LINE.search(line)
            if not match or match.group(1) not in rows:
                return []
            ticker = match.group(1)
            out: list[Span] = [(0, len(line), self._row_handler(rows[ticker]))]
            if (col := line.find(ADD_BUTTON)) >= 0:
                out.append((col, col + len(ADD_BUTTON), self._add_handler(ticker)))
            return out

        return clickable(to_formatted_text(self._rich(self._search_body())), spans)

    def _row_handler(self, index: int) -> MouseHandler:
        def handler(event: MouseEvent) -> object:
            if event.event_type == MouseEventType.MOUSE_UP:
                if self.search_sel == index:
                    self.open_details()
                else:
                    self.search_sel = index
            elif event.event_type == MouseEventType.SCROLL_UP:
                self.move(-1)
            elif event.event_type == MouseEventType.SCROLL_DOWN:
                self.move(1)
            else:
                return NotImplemented
            return None

        return handler

    def _add_handler(self, ticker: str) -> MouseHandler:
        def handler(event: MouseEvent) -> object:
            if event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            self.add_ticker(ticker)
            return None

        return handler

    def _wallet_body(self) -> RenderableType:
        if not self.wallet_loaded:
            return Text("  Carregando carteira...", style="muted")
        if not self.wallet:
            return Group(
                Text(),
                Text("  Sua carteira está vazia."),
                Text("  Digite no campo acima o nome ou o ticker de um fundo.", style="muted"),
            )
        start, end = self._visible(len(self.wallet), self.wallet_sel, self._height() - 3)
        return assets_table(
            self.wallet[start:end],
            self._width(),
            selected=self.wallet_sel - start,
            flat=True,
        )

    def _search_body(self) -> RenderableType:
        term = self.search_buffer.text.strip()
        if not self.catalog:
            return Text("  Carregando a lista de ativos...", style="muted")
        if not self.hits:
            return Text(f'  Nenhum ativo encontrado para "{term}".', style="muted")
        start, end = self._visible(len(self.hits), self.search_sel, self._height() - 3)
        wallet = {v.ticker for v in self.wallet}
        return search_table(
            self.hits[start:end],
            wallet,
            self.search_views,
            selected=self.search_sel - start,
            flat=True,
            start=start,
            pending=self.quotes_pending,
            buttons=True,
        )

    def _status(self) -> StyleAndTextTuples:
        if self.mode == Mode.CONFIRM and self.confirmation:
            return [("class:status.warn bold", f" {self.confirmation.question}")]
        if self.busy:
            spin = SPINNER[self.tick % len(SPINNER)]
            self.tick += 1
            return [("class:status.busy", f" {spin} {self.busy}...")]
        if self.message:
            kind, text = self.message
            return [(f"class:status.{kind}", f" {text}")]
        return [("", "")]

    def _footer(self) -> StyleAndTextTuples:
        if self.mode == Mode.CONFIRM:
            keys = [("S", "Sim"), ("N", "Não")]
        elif self.mode == Mode.DETAILS:
            keys = []
            if self.details and not self.details.in_wallet:
                keys.append(("A", "Adicionar à carteira"))
            if self.details and self.details.in_wallet:
                keys.append(("R", "Remover"))
            keys += [("U", "Atualizar"), ("Esc", "Voltar")]
        elif self.searching:
            keys = [
                ("↑/↓", "Navegar"),
                ("Enter", "Abrir"),
                ("Clique", "+ Adicionar"),
                ("Esc", "Limpar busca"),
            ]
        else:
            keys = [
                ("↑/↓", "Navegar"),
                ("Enter", "Detalhes"),
                ("Del", "Remover"),
                ("Ctrl+R", "Atualizar"),
                ("Esc", "Sair"),
            ]
        out: StyleAndTextTuples = []
        for key, label in keys:
            out += [("class:footer.key", f" {key} "), ("class:footer", f"{label} ")]
        return out

    # --- layout e teclas ---------------------------------------------------------

    def _build_app(self) -> Application:
        listing = Condition(lambda: self.mode == Mode.LIST)
        in_search = Condition(lambda: self.mode == Mode.LIST and self.searching)
        wallet_list = Condition(lambda: self.mode == Mode.LIST and not self.searching)
        details = Condition(lambda: self.mode == Mode.DETAILS)
        confirming = Condition(lambda: self.mode == Mode.CONFIRM)

        search_box = Frame(
            Window(
                BufferControl(
                    self.search_buffer,
                    input_processors=[
                        BeforeInput("⌕ ", style="class:searchbox.icon"),
                        Placeholder(PLACEHOLDER),
                    ],
                ),
                height=1,
                style="class:searchbox",
            )
        )
        self.body_window = Window(
            FormattedTextControl(self._body, focusable=True, show_cursor=False),
            wrap_lines=False,
        )
        body = HSplit(
            [
                ConditionalContainer(search_box, filter=~details),
                Window(FormattedTextControl(self._heading), height=1),
                Window(height=1, char="─", style="class:rule"),
                self.body_window,
            ]
        )
        root = HSplit(
            [
                Frame(body, title="ATIVOS-CLI"),
                Window(FormattedTextControl(self._status), height=1),
                Window(FormattedTextControl(self._footer), height=1),
            ]
        )

        kb = KeyBindings()

        @kb.add("c-c")
        def _quit(event) -> None:
            event.app.exit()

        @kb.add("up", filter=listing)
        @kb.add("c-p", filter=listing)
        def _up(event) -> None:
            self.move(-1)

        @kb.add("down", filter=listing)
        @kb.add("c-n", filter=listing)
        def _down(event) -> None:
            self.move(1)

        @kb.add("pageup", filter=listing)
        def _pgup(event) -> None:
            self.move(-10)

        @kb.add("pagedown", filter=listing)
        def _pgdown(event) -> None:
            self.move(10)

        @kb.add("enter", filter=listing)
        def _enter(event) -> None:
            self.open_details()

        # O campo de busca fica sempre em foco na lista: letras são digitadas, e as ações
        # da carteira usam teclas que não escrevem texto.
        @kb.add("delete", filter=wallet_list)
        def _remove(event) -> None:
            self.ask_remove()

        @kb.add("c-r", filter=wallet_list | details)
        def _refresh(event) -> None:
            self.refresh()

        @kb.add("escape", filter=wallet_list, eager=True)
        def _esc_wallet(event) -> None:
            event.app.exit()

        @kb.add("escape", filter=in_search, eager=True)
        def _esc_search(event) -> None:
            self.clear_search()

        for key in ("r", "R"):
            kb.add(key, filter=details)(lambda e: self.ask_remove())
        for key in ("u", "U"):
            kb.add(key, filter=details)(lambda e: self.refresh())
        for key in ("a", "A", "+"):
            kb.add(key, filter=details)(lambda e: self.add_current())
        for key in ("escape", "q", "Q", "backspace", "left"):
            kb.add(key, filter=details, eager=key == "escape")(lambda e: self.close_details())

        for key in ("s", "S", "y", "Y"):
            kb.add(key, filter=confirming)(lambda e: self.answer(True))
        for key in ("n", "N", "escape"):
            kb.add(key, filter=confirming, eager=key == "escape")(lambda e: self.answer(False))

        app = Application(
            layout=Layout(
                root,
                focused_element=self.search_buffer,
            ),
            key_bindings=merge_key_bindings([load_basic_bindings(), kb]),
            style=STYLE,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.12,
        )
        app.ttimeoutlen = 0.05
        return app
