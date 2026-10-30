"""Comandos da CLI. Interpreta argumentos, controla a navegação e delega ao serviço."""

import functools
import json
import logging
from dataclasses import dataclass, field
from datetime import date

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from ativos_cli import __version__, config
from ativos_cli.errors import AtivosError
from ativos_cli.models import AssetView, DisplayStatus, FetchResult, FetchStatus
from ativos_cli.repositories.asset_repository import AssetRepository
from ativos_cli.repositories.database import connect
from ativos_cli.scraper.parser import is_valid_ticker, normalize_ticker
from ativos_cli.scraper.runner import ScrapyFetcher
from ativos_cli.services import Fetcher
from ativos_cli.services.asset_service import AssetService
from ativos_cli.services.search_service import SearchService
from ativos_cli.ui import prompts
from ativos_cli.ui.tables import (
    asset_title,
    details_panel,
    fetch_note,
    plain_table,
)
from ativos_cli.ui.theme import make_console
from ativos_cli.utils.dates import format_date, format_datetime
from ativos_cli.utils.money import format_brl

log = logging.getLogger(__name__)

EPILOG = """\
[bold]Exemplos[/bold]

  ativos                      atualiza e mostra a carteira
  ativos MXRF11               consulta um ativo
  ativos search "maxi renda"  pesquisa por nome ou ticker aproximado
  ativos add KNCR11           adiciona à carteira
  ativos remove KNCR11        remove da carteira (mantém o histórico)
  ativos refresh              atualiza todos os ativos da carteira
  ativos catalog update       baixa o catálogo usado na pesquisa

Fonte dos dados: fiis.com.br
"""

app = typer.Typer(
    name="ativos",
    help="Acompanhe datas-com, rendimentos e cotações-base de FIIs pelo terminal.",
    epilog=EPILOG,
    rich_markup_mode="rich",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
catalog_app = typer.Typer(help="Catálogo local de ativos usado na pesquisa.", no_args_is_help=True)
app.add_typer(catalog_app, name="catalog")


def today() -> date:
    """Data local de hoje (os testes substituem para fixar o mês)."""
    return date.today()


def build_fetcher(debug: bool) -> Fetcher:
    """Ponto de troca da fonte de dados (os testes substituem por um fetcher falso)."""
    return ScrapyFetcher(debug=debug)


@dataclass
class State:
    debug: bool = False
    console: Console = field(default_factory=make_console)
    err: Console = field(default_factory=lambda: make_console(stderr=True))
    _service: AssetService | None = None
    _search: SearchService | None = None

    def _build(self) -> None:
        repo = AssetRepository(connect(config.db_path()))
        fetcher = build_fetcher(self.debug)
        self._service = AssetService(repo, fetcher)
        self._search = SearchService(repo, fetcher)

    @property
    def service(self) -> AssetService:
        if self._service is None:
            self._build()
        return self._service

    @property
    def search(self) -> SearchService:
        if self._search is None:
            self._build()
        return self._search


_state = State()


def handle_errors(func):
    """Converte erros esperados em mensagens curtas (traceback só com --debug)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AtivosError as exc:
            if _state.debug:
                _state.err.print_exception()
            _state.err.print(Text(f"Erro: {exc}", style="fail"))
            raise typer.Exit(1) from None

    return wrapper


def _version(value: bool) -> None:
    if value:
        typer.echo(f"ativos-cli {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
@handle_errors
def main(
    ctx: typer.Context,
    debug: bool = typer.Option(
        False, "--debug", envvar="ATIVOS_DEBUG", help="Mostra detalhes técnicos dos erros."
    ),
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version, is_eager=True, help="Mostra a versão."
    ),
) -> None:
    """Sem argumentos, atualiza a carteira e mostra seus ativos."""
    global _state
    _state = State(debug=debug)
    if debug:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    if ctx.invoked_subcommand is None:
        open_wallet(_state)


# --- consulta individual -------------------------------------------------------


def view_to_dict(view: AssetView) -> dict:
    snap = view.valid
    return {
        "ticker": view.ticker,
        "nome": view.name,
        "datacom": snap.datacom.isoformat() if snap and snap.datacom else None,
        "rendimento": str(snap.rendimento) if snap and snap.rendimento is not None else None,
        "cotacao_base": str(snap.cotacao_base) if snap and snap.cotacao_base is not None else None,
        "rendimento_pct": (
            str(snap.rendimento_pct) if snap and snap.rendimento_pct is not None else None
        ),
        "data_pagamento": (
            snap.data_pagamento.isoformat() if snap and snap.data_pagamento else None
        ),
        "status": view.status.name.lower(),
        "desatualizado": view.stale,
        "consultado_em": snap.fetched_at.isoformat() if snap else None,
        "erro": view.last_error,
        "fonte": snap.source_url if snap else None,
        "na_carteira": view.in_wallet,
    }


def print_json(state: State, payload) -> None:
    state.console.print_json(json.dumps(payload, ensure_ascii=False))


def show_asset(state: State, raw_ticker: str, details: bool = False) -> AssetView:
    console = state.console
    ticker = normalize_ticker(raw_ticker)
    with console.status(f"Consultando {ticker} no {config.SOURCE_NAME}..."):
        view = state.service.lookup(ticker)

    console.print(plain_table([view], console.width, today()))
    if view.status != DisplayStatus.UPDATED and (note := fetch_note(view)):
        console.print(note)
    if details:
        console.print()
        console.print(details_panel(view, console.width))
    return view


@app.command("show")
@handle_errors
def show_command(
    ticker: str = typer.Argument(..., help="Ticker do ativo, ex.: MXRF11."),
    details: bool = typer.Option(False, "--detalhes", "-d", help="Mostra todos os detalhes."),
    as_json: bool = typer.Option(False, "--json", help="Saída em JSON, para scripts."),
) -> None:
    """Consulta um ativo (o mesmo que [bold]ativos TICKER[/bold])."""
    if as_json:
        print_json(_state, view_to_dict(_state.service.lookup(ticker)))
    else:
        show_asset(_state, ticker, details=details)


# --- carteira --------------------------------------------------------------------


def add_asset(state: State, raw_ticker: str) -> Text:
    """Adiciona e devolve a mensagem de resultado."""
    ticker = normalize_ticker(raw_ticker)
    with state.console.status(f"Validando {ticker}..."):
        outcome = state.service.add(ticker)
    if not outcome.added:
        message = Text(f"  {ticker} já está na sua carteira.", style="muted")
    else:
        message = Text(f"  {ticker} adicionado à carteira.", style="ok")
        if outcome.warning:
            message.append(f"\n  {outcome.warning}", style="warn")
    return message


@app.command("add")
@handle_errors
def add_command(ticker: str = typer.Argument(..., help="Ticker do ativo.")) -> None:
    """Adiciona um ativo à carteira (valida o ativo e evita duplicatas)."""
    _state.console.print(add_asset(_state, ticker))


@app.command("remove")
@handle_errors
def remove_command(
    ticker: str = typer.Argument(..., help="Ticker do ativo."),
    purge: bool = typer.Option(False, "--purge", help="Apaga também o histórico de consultas."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Não pede confirmação."),
) -> None:
    """Remove um ativo da carteira. O histórico é mantido, a menos que use --purge."""
    service = _state.service
    ticker = normalize_ticker(ticker)
    if not service.repo.in_wallet(ticker) and not purge:
        raise AtivosError(f"{ticker} não está na carteira.")
    if not yes:
        if prompts.is_interactive():
            if not prompts.confirm(_state.console, removal_question(service, ticker, purge)):
                _state.console.print(Text("  Remoção cancelada.", style="muted"))
                return
        elif purge:
            raise AtivosError("Use --yes para confirmar a exclusão do histórico.")
    if service.remove(ticker, purge=purge):
        msg = "removido da carteira e histórico apagado" if purge else "removido da carteira"
        _state.console.print(Text(f"  {ticker} {msg}.", style="ok"))
    else:
        _state.console.print(Text(f"  Nada a remover para {ticker}.", style="muted"))


def removal_question(service: AssetService, ticker: str, purge: bool) -> str:
    count = service.history_count(ticker)
    if purge:
        return f"Remover {ticker} e apagar {count} consulta(s) do histórico?"
    if count:
        return f"Remover {ticker} da carteira? O histórico ({count} consulta(s)) será mantido."
    return f"Remover {ticker} da carteira?"


def refresh_with_progress(state: State, tickers: list[str] | None):
    total = len(tickers) if tickers else len(state.service.repo.wallet_tickers())
    progress = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=state.console,
        transient=True,
    )
    with progress:
        task = progress.add_task(f"Consultando o {config.SOURCE_NAME}", total=total)

        def advance(result: FetchResult) -> None:
            mark = "ok" if result.status == FetchStatus.OK else "falha"
            progress.update(task, advance=1, description=f"{result.ticker} ({mark})")

        return state.service.refresh(tickers, on_progress=advance)


@app.command("refresh")
@handle_errors
def refresh_command(
    ticker: str | None = typer.Argument(None, help="Atualiza só este ativo."),
    as_json: bool = typer.Option(False, "--json", help="Saída em JSON, para scripts."),
) -> None:
    """Atualiza os dados da carteira (ou de um ativo) e mostra o resumo."""
    console = _state.console
    tickers = [ticker] if ticker else None
    if not tickers and not _state.service.repo.wallet_tickers():
        console.print(Text("  Sua carteira está vazia. Use: ativos add TICKER", style="muted"))
        return
    summary = refresh_with_progress(_state, tickers)
    if as_json:
        print_json(_state, [view_to_dict(v) for v in summary.views])
    else:
        print_summary(_state, summary)
    if summary.failed:
        raise typer.Exit(1)


def print_summary(state: State, summary) -> None:
    """Tabela simples dos ativos atualizados, com as falhas listadas embaixo."""
    console = state.console
    console.print(plain_table(summary.views, console.width, today()))
    for view in summary.failed:
        error = view.last_error or "sem dados"
        console.print(Text(f"  {view.ticker}: {error}", style="fail"))


@app.command("history")
@handle_errors
def history_command(
    ticker: str = typer.Argument(..., help="Ticker do ativo."),
    limit: int = typer.Option(20, "--limit", "-n", help="Quantidade de consultas."),
) -> None:
    """Mostra o histórico de consultas gravadas de um ativo."""
    ticker = normalize_ticker(ticker)
    snapshots = _state.service.repo.history(ticker, limit=limit)
    if not snapshots:
        _state.console.print(Text(f"  Nenhuma consulta gravada para {ticker}.", style="muted"))
        return
    table = Table(header_style="bold", border_style="border")
    table.add_column("Consulta", no_wrap=True)
    table.add_column("Resultado", no_wrap=True)
    table.add_column("Data-com", style="datacom", no_wrap=True)
    table.add_column("Rendimento", justify="right", no_wrap=True)
    table.add_column("Cotação-base", justify="right", no_wrap=True)
    for snap in snapshots:
        ok = snap.status == FetchStatus.OK
        table.add_row(
            format_datetime(snap.fetched_at),
            Text("Sucesso", "ok") if ok else Text(snap.error or "Falha", "fail"),
            format_date(snap.datacom) if ok else "",
            format_brl(snap.rendimento) if ok else "",
            format_brl(snap.cotacao_base) if ok else "",
        )
    _state.console.print(asset_title(_state.service.view(ticker)))
    _state.console.print(table)


def open_wallet(state: State) -> None:
    if not state.service.repo.wallet_tickers():
        state.console.print(
            Text("  Sua carteira está vazia. Use: ativos add TICKER", style="muted")
        )
        return
    print_summary(state, refresh_with_progress(state, None))


# --- pesquisa ----------------------------------------------------------------------


def refresh_catalog_for_search(state: State) -> bool:
    """Baixa a lista de ativos do site a cada pesquisa.

    Se a consulta falhar, usa o catálogo salvo da última pesquisa bem-sucedida.
    """
    console = state.console
    try:
        with console.status(f"Pesquisando no {config.SOURCE_NAME}..."):
            state.search.update_catalog()
        return True
    except AtivosError as exc:
        status = state.search.status()
        if status.missing:
            console.print(Text(f"  Não foi possível pesquisar: {exc}", style="fail"))
            return False
        when = format_datetime(status.updated_at) if status.updated_at else "consultas anteriores"
        console.print(Text(f"  {exc} Usando a lista salva ({when}).", style="warn"))
        return True


def update_catalog(state: State) -> int:
    with state.console.status(f"Baixando o catálogo do {config.SOURCE_NAME}..."):
        count = state.search.update_catalog()
    state.console.print(Text(f"  Catálogo atualizado: {count} ativos.", style="ok"))
    return count


def search_views(state: State, hits: list) -> dict[str, AssetView]:
    """Consulta no site a página de cada resultado, para mostrar a data-com na tabela.

    Falhas não interrompem a pesquisa: o ativo aparece com o último dado salvo, se houver.
    """
    if not hits:
        return {}
    service = state.service
    tickers = [h.entry.ticker for h in hits]
    views = {t: service.view(t) for t in tickers}
    stale = [t for t in tickers if not service.is_fresh(t, config.SEARCH_FRESH_FOR)]
    if stale:
        views.update((v.ticker, v) for v in refresh_with_progress(state, stale).views)
    return views


def search_date(view: AssetView | None) -> str | None:
    if view is None or view.valid is None or view.valid.datacom is None:
        return None
    return view.valid.datacom.isoformat()


def run_search(state: State, term: str, as_json: bool = False) -> None:
    console = state.console
    if not refresh_catalog_for_search(state):
        if is_valid_ticker(normalize_ticker(term)):
            console.print(Text(f"  Ou consulte direto: ativos {term.upper()}", style="muted"))
        return

    hits = state.search.search(term, limit=config.SEARCH_LIMIT)
    views = search_views(state, hits)
    if as_json:
        print_json(
            state,
            [
                {
                    "ticker": h.entry.ticker,
                    "nome": h.entry.name,
                    "datacom": search_date(views.get(h.entry.ticker)),
                }
                for h in hits
            ],
        )
        return

    if not hits:
        console.print(Text(f'  Nenhum ativo encontrado para "{term}".', style="muted"))
        if is_valid_ticker(normalize_ticker(term)):
            console.print(Text(f"  Tente consultar direto: ativos {term.upper()}", style="muted"))
        return
    console.print(plain_table([views[h.entry.ticker] for h in hits], console.width, today()))


@app.command("search")
@handle_errors
def search_command(
    term: list[str] = typer.Argument(..., help="Ticker ou nome aproximado."),
    as_json: bool = typer.Option(False, "--json", help="Saída em JSON, para scripts."),
) -> None:
    """Pesquisa ativos por ticker ou nome aproximado no fiis.com.br."""
    text = " ".join(term)
    run_search(_state, text, as_json=as_json)


@catalog_app.command("update")
@handle_errors
def catalog_update_command() -> None:
    """Baixa a lista de fundos do fiis.com.br para a pesquisa."""
    update_catalog(_state)


@catalog_app.command("status")
@handle_errors
def catalog_status_command() -> None:
    """Mostra o tamanho e a data do catálogo local."""
    status = _state.search.status()
    if status.missing:
        _state.console.print("  Catálogo vazio. Execute: ativos catalog update")
        return
    line = Text(f"  {status.count} ativos, atualizado em {format_datetime(status.updated_at)}")
    if status.stale:
        line.append(" (desatualizado)", style="warn")
    _state.console.print(line)
