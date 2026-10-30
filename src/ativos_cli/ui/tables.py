"""Renderização de painéis e tabelas com Rich."""

from rich import box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ativos_cli import config
from ativos_cli.models import AssetView, DisplayStatus, FetchStatus
from ativos_cli.services.search_service import SearchHit
from ativos_cli.utils.dates import format_date, format_datetime
from ativos_cli.utils.money import format_brl, format_percent, yield_percent

# Rótulo do botão clicável na tabela de resultados (ver ui/app.py).
ADD_BUTTON = " + Adicionar "
IN_WALLET = "✓ Na carteira"

# Abaixo destas larguras, colunas secundárias somem ou ficam compactas.
WIDE = 84
NARROW = 64
# Tabela simples: recuo da borda e largura mínima para mostrar o pagamento.
INDENT = 2
PLAIN_WIDE = 76


def header(title: str, subtitle: str, width: int) -> Panel:
    grid = Table.grid(expand=True)
    grid.add_column()
    grid.add_column(justify="right")
    grid.add_row(Text("ATIVOS-CLI", style="brand"), Text(title, style="brand"))
    grid.add_row(Text(subtitle, style="muted"), "")
    return Panel(grid, box=box.ROUNDED, border_style="border", width=min(width, 80))


def status_text(view: AssetView, compact: bool = False) -> Text:
    if view.status == DisplayStatus.UPDATED:
        return Text("OK" if compact else "Atualizado", style="ok")
    if view.status == DisplayStatus.CACHED:
        if view.last_error:
            return Text("Falha" if compact else "Falha (cache)", style="fail")
        if view.stale:
            return Text("Antigo" if compact else "Cache antigo", style="warn")
        return Text("Cache" if compact else "Em cache", style="warn")
    if view.status == DisplayStatus.FAILED:
        return Text("Falha", style="fail")
    return Text("Sem dados" if not compact else "N/D", style="muted")


def assets_table(
    views: list[AssetView],
    width: int,
    show_status: bool = True,
    selected: int | None = None,
    numbered: bool = False,
    flat: bool = False,
) -> Table:
    """Tabela com uma linha por ativo; data-com é a coluna em destaque."""
    show_payment = width >= WIDE
    compact = width < NARROW
    table = Table(
        box=box.SIMPLE_HEAD if flat else box.HEAVY_HEAD,
        border_style="border",
        header_style="bold",
        expand=flat,
    )
    if numbered:
        table.add_column("#", justify="right", style="muted", no_wrap=True)
    table.add_column("Ativo", style="ticker", no_wrap=True)
    table.add_column("Data-com", style="datacom", no_wrap=True)
    table.add_column("Rendimento", style="value", justify="right", no_wrap=True)
    table.add_column("Cotação-base", style="value", justify="right", no_wrap=True)
    if show_payment:
        table.add_column("Pagamento", style="muted", no_wrap=True)
    if show_status:
        table.add_column("Status", no_wrap=True)

    for index, view in enumerate(views):
        snap = view.valid
        row: list[RenderableType] = [str(index + 1)] if numbered else []
        if flat:
            ticker = f"❯ {view.ticker}" if index == selected else f"  {view.ticker}"
        else:
            ticker = view.ticker
        row += [
            ticker,
            format_date(snap.datacom if snap else None),
            format_brl(snap.rendimento if snap else None),
            format_brl(snap.cotacao_base if snap else None),
        ]
        if show_payment:
            row.append(format_date(snap.data_pagamento if snap else None))
        if show_status:
            status = status_text(view, compact)
            row.append(Text("● ", style=status.style) + status if flat else status)
        table.add_row(*row, style="selected" if index == selected else None)
    return table


def plain_table(views: list[AssetView], width: int) -> Padding:
    """Tabela enxuta, uma linha por ativo, para imprimir direto no terminal.

    Fica recuada da borda do terminal. Em terminais estreitos, a coluna de pagamento
    some para caber o essencial.
    """
    show_payment = width >= PLAIN_WIDE
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False, show_edge=False)
    for column in ("Ativo", "Data-com", "Rendimento", "Rend. %", "Cotação-base"):
        table.add_column(column, no_wrap=True)
    if show_payment:
        table.add_column("Pagamento", no_wrap=True)
    for view in views:
        snap = view.valid
        rendimento = snap.rendimento if snap else None
        cotacao = snap.cotacao_base if snap else None
        row = [
            view.ticker,
            format_date(snap.datacom if snap else None),
            format_brl(rendimento),
            format_percent(yield_percent(rendimento, cotacao)),
            format_brl(cotacao),
        ]
        if show_payment:
            row.append(format_date(snap.data_pagamento if snap else None))
        table.add_row(*row)
    return Padding(table, (0, 0, 0, INDENT), expand=False)


def asset_title(view: AssetView) -> Text:
    text = Text("  ")
    text.append(view.ticker, style="ticker")
    if view.name:
        text.append(f" — {view.name}")
    return text


def fetch_note(view: AssetView) -> Text | None:
    """Explica de onde vêm os dados quando não são de uma coleta bem-sucedida agora."""
    snap = view.valid
    if view.status == DisplayStatus.UPDATED and snap:
        return Text(f"  Atualizado em {format_datetime(snap.fetched_at)}", style="muted")
    if view.last_error and snap:
        return Text(
            f"  Não foi possível atualizar: {view.last_error}\n"
            f"  Exibindo o último dado válido, de {format_datetime(snap.fetched_at)}.",
            style="warn",
        )
    if snap:
        note = f"  Dados em cache de {format_datetime(snap.fetched_at)}"
        return Text(note + (" (potencialmente desatualizados)." if view.stale else "."), "muted")
    if view.last_error:
        return Text(f"  {view.last_error}", style="fail")
    return None


def search_table(
    hits: list[SearchHit],
    wallet: set[str],
    views: dict[str, AssetView] | None = None,
    selected: int | None = None,
    flat: bool = False,
    start: int = 0,
    pending: set[str] | None = None,
    buttons: bool = False,
) -> Table:
    """Resultados da pesquisa. Com `views`, inclui data-com e rendimento de cada ativo.

    `start` é a posição da primeira linha na lista completa (numeração ao rolar),
    `pending` são os ativos ainda sendo consultados no site e `buttons` acrescenta a
    coluna com o botão de adicionar à carteira.
    """
    pending = pending or set()
    table = Table(
        box=box.SIMPLE_HEAD if flat else box.HEAVY_HEAD,
        border_style="border",
        header_style="bold",
        expand=flat,
    )
    table.add_column("#", justify="right", style="muted", no_wrap=True)
    table.add_column("Ticker", style="ticker", no_wrap=True)
    table.add_column("Nome", overflow="ellipsis", ratio=1 if flat else None)
    if views is not None:
        table.add_column("Data-com", style="datacom", no_wrap=True)
        table.add_column("Rendimento", style="value", justify="right", no_wrap=True)
    if buttons:
        table.add_column("", no_wrap=True)
    for i, hit in enumerate(hits):
        ticker = hit.entry.ticker
        name = Text(hit.entry.name)
        if ticker in wallet and not buttons:
            name.append("  na carteira", style="muted")
        marker = "❯ " if i == selected else ""
        row: list[RenderableType] = [f"{marker}{start + i + 1}", ticker, name]
        if views is not None:
            snap = views[ticker].valid if ticker in views else None
            if snap is None and ticker in pending:
                row += [Text("consultando…", style="muted"), ""]
            else:
                row += [
                    format_date(snap.datacom if snap else None),
                    format_brl(snap.rendimento if snap else None),
                ]
        if buttons:
            in_wallet = ticker in wallet
            row.append(Text(IN_WALLET, "muted") if in_wallet else Text(ADD_BUTTON, "button"))
        table.add_row(*row, style="selected" if i == selected else None)
    return table


def details_panel(view: AssetView, width: int, flat: bool = False) -> Panel:
    snap = view.valid
    attempt = view.last_attempt
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", no_wrap=True)
    grid.add_column()

    grid.add_row("Ticker", Text(view.ticker, style="ticker"))
    grid.add_row("Nome", view.name or "N/D")
    grid.add_row("Data-com", Text(format_date(snap.datacom if snap else None), style="datacom"))
    grid.add_row("Rendimento por cota", format_brl(snap.rendimento if snap else None))
    grid.add_row("Cotação-base", format_brl(snap.cotacao_base if snap else None))
    grid.add_row("Data de pagamento", format_date(snap.data_pagamento if snap else None))
    grid.add_row("Cotação atual", format_brl(snap.cotacao_atual if snap else None))
    grid.add_row("", "")
    grid.add_row("Última consulta válida", format_datetime(snap.fetched_at if snap else None))
    origin = config.SOURCE_NAME
    if snap and snap.source_field:
        origin += f" (campos {snap.source_field})"
    grid.add_row("Origem dos dados", origin)
    grid.add_row("URL", (snap or attempt).source_url if (snap or attempt) else "N/D")

    if attempt is None:
        situation = Text("Nunca consultado", style="muted")
    elif attempt.status == FetchStatus.OK:
        situation = Text(f"Sucesso em {format_datetime(attempt.fetched_at)}", style="ok")
    else:
        situation = Text(
            f"Falha em {format_datetime(attempt.fetched_at)}: {attempt.error or 'erro'}",
            style="fail",
        )
    grid.add_row("Situação da última coleta", situation)
    grid.add_row("Na carteira", "Sim" if view.in_wallet else "Não")
    if flat:
        return Panel(grid, box=box.SIMPLE, padding=(0, 1))
    return Panel(grid, box=box.ROUNDED, border_style="border", width=min(width, 80))


def key_hints(*rows: list[tuple[str, str]]) -> Group:
    lines = []
    for row in rows:
        line = Text("  ")
        for i, (key, label) in enumerate(row):
            if i:
                line.append("  ")
            line.append(f"[{key}]", style="key")
            line.append(f" {label}")
        lines.append(line)
    return Group(*lines)
