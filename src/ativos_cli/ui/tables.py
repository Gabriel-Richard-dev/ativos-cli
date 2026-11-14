"""Renderização de painéis e tabelas com Rich."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from rich import box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ativos_cli import config
from ativos_cli.models import AssetType, AssetView, DisplayStatus, FetchStatus
from ativos_cli.services.search_service import SearchHit
from ativos_cli.utils.dates import format_date, format_datetime
from ativos_cli.utils.money import format_brl, format_percent

# Rótulo do botão clicável na tabela de resultados (ver ui/app.py).
ADD_BUTTON = " + Adicionar "
IN_WALLET = "✓ Na carteira"

# Abaixo destas larguras, colunas secundárias somem ou ficam compactas.
WIDE = 84
NARROW = 64
# Tabela simples: recuo da borda e largura mínima para mostrar o pagamento.
INDENT = 2
DASH = "—"
PROVISIONAL_NOTE = "* cotação provisória da B3; o fechamento oficial sai na manhã seguinte."
PLAIN_WIDE = 76
# A partir desta largura, as colunas do rendimento anterior ficam ao lado das do mês.
PLAIN_FULL_WIDE = 122


def sort_by_datacom(views: list[AssetView], today: date | None = None) -> list[AssetView]:
    """Da data-com mais antiga para a mais nova, começando pelas do mês de `today`.

    Quem ainda não tem data-com no mês (a linha do mês fica com traços) vem depois,
    também da mais antiga para a mais nova; ativos sem data-com nenhuma vão para o fim.
    """
    month_start = (today or date.today()).replace(day=1)

    def key(view: AssetView) -> tuple:
        datacom = view.valid.datacom if view.valid else None
        if datacom is None:
            return (2, date.min, view.ticker)
        return (0 if datacom >= month_start else 1, datacom, view.ticker)

    return sorted(views, key=key)


def group_by_type(
    views: list[AssetView], today: date | None = None
) -> list[tuple[AssetType, list[AssetView]]]:
    """FIIs e depois ETFs, cada grupo ordenado por data-com (grupos vazios ficam de fora)."""
    groups = []
    for asset_type in AssetType:
        members = [v for v in views if v.asset_type == asset_type]
        if members:
            groups.append((asset_type, sort_by_datacom(members, today)))
    return groups


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
            ticker = Text(f"❯ {view.ticker}" if index == selected else f"  {view.ticker}")
        else:
            ticker = Text(view.ticker)
        if view.asset_type == AssetType.ETF:
            ticker.append(" ETF", style="muted")
        row += [
            ticker,
            format_date(snap.datacom if snap else None),
            rendimento_text(snap),
            format_brl(snap.cotacao_base if snap else None),
        ]
        if show_payment:
            row.append(format_date(snap.data_pagamento if snap else None))
        if show_status:
            status = status_text(view, compact)
            row.append(Text("● ", style=status.style) + status if flat else status)
        table.add_row(*row, style="selected" if index == selected else None)
    return table


def plain_table(views: list[AssetView], width: int, today: date) -> RenderableType:
    """Tabela enxuta, uma linha por ativo, para imprimir direto no terminal.

    Só mostra rendimentos com data-com no mês de `today` em diante; os de meses
    anteriores viram traços. As colunas "ant." trazem o rendimento anterior ao do mês:
    enquanto o do mês não sai, é o último rendimento coletado. Num terminal largo elas
    ficam à direita de um divisor vertical; num estreito, numa segunda tabela logo
    abaixo, para nada quebrar de linha. Fica recuada da borda do terminal e, abaixo de
    `PLAIN_WIDE` colunas, a coluna Pagamento some.
    """
    side_by_side = width >= PLAIN_FULL_WIDE
    show_payment = width >= PLAIN_WIDE
    month = _plain("Ativo", "Data-com", "Rendimento", "Rend. %", "Cotação-base")
    if show_payment:
        month.add_column("Pagamento", no_wrap=True)
    # Na tabela de baixo, o ativo se repete para cada linha ter dono.
    ticker_column = [] if side_by_side else ["Ativo"]
    previous = _plain(*ticker_column, "Data-com ant.", "Rend. ant.", "Rend. % ant.")
    month_start = today.replace(day=1)
    provisional = False
    for view in views:
        snap = view.valid
        if snap is None or snap.datacom is None:
            month.add_row(view.ticker, *[DASH] * (len(month.columns) - 1))
            previous.add_row(*([] if side_by_side else [view.ticker]), DASH, DASH, DASH)
            continue
        current = snap.datacom >= month_start
        if current:
            row = [
                view.ticker,
                format_date(snap.datacom),
                rendimento_text(snap),
                # Sem cotação nenhuma ainda: traço. Cotação do dia, antes do fechamento
                # oficial da B3: marcada com asterisco.
                marked(format_percent, snap.rendimento_pct, snap.cotacao_provisoria),
                marked(format_brl, snap.cotacao_base, snap.cotacao_provisoria),
            ]
            if show_payment:
                row.append(format_date(snap.data_pagamento))
            provisional = provisional or (snap.cotacao_provisoria and snap.cotacao_base is not None)
            previous.add_row(
                *([] if side_by_side else [view.ticker]),
                dash_or(format_date, snap.datacom_anterior),
                dash_or(format_brl, snap.rendimento_anterior),
                dash_or(format_percent, snap.rendimento_pct_anterior),
            )
        else:
            row = [view.ticker, *[DASH] * (len(month.columns) - 1)]
            # O rendimento do mês ainda não saiu: o último coletado é o anterior.
            previous.add_row(
                *([] if side_by_side else [view.ticker]),
                format_date(snap.datacom),
                dash_or(format_brl, snap.rendimento),
                marked(format_percent, snap.rendimento_pct, snap.cotacao_provisoria),
            )
            provisional = provisional or (
                snap.cotacao_provisoria and snap.rendimento_pct is not None
            )
        month.add_row(*row)
    if side_by_side:
        # Divisor entre o mês e o anterior; cruza a linha abaixo do cabeçalho.
        divider = Text("\n".join(["  │  ", "──┼──", *["  │  "] * len(views)]), style="border")
        table: RenderableType = Table.grid()
        table.add_row(month, divider, previous)
    else:
        table = Group(month, Text(""), previous)
    body = Padding(table, (0, 0, 0, INDENT), expand=False)
    if not provisional:
        return body
    note = Text(f"\n{' ' * INDENT}{PROVISIONAL_NOTE}", style="muted")
    return Group(body, note)


def _plain(*headers: str) -> Table:
    # Linha do cabeçalho na mesma cor do divisor vertical, para o cruzamento não destoar.
    table = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold",
        border_style="border",
        pad_edge=False,
        show_edge=False,
    )
    for header in headers:
        table.add_column(header, no_wrap=True)
    return table


MONTHS = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)  # fmt: skip
# A partir desta largura, o último rendimento fica ao lado do mês.
COMPACT_WIDE = 90


def month_title(today: date) -> str:
    return f"{MONTHS[today.month - 1]}/{today.year}"


def short_date(value: date, today: date) -> str:
    """ "06/11" no ano corrente; com o ano, se for outro."""
    return value.strftime("%d/%m" if value.year == today.year else "%d/%m/%Y")


def short_brl(value: Decimal | None) -> str:
    """Rendimento com até 4 casas: R$ 0,1916249 -> R$ 0,1916; R$ 0,10 continua R$ 0,10."""
    if value is None:
        return DASH
    return format_brl(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize())


def short_percent(value: Decimal | None, provisional: bool = False) -> str:
    if value is None:
        return ""
    text = format_percent(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return f"{text}*" if provisional else text


def compact_list(
    groups: list[tuple[str | None, list[AssetView]]], today: date, width: int = 200
) -> RenderableType:
    """Visão enxuta: uma tabela por grupo, com cabeçalho, datas curtas e valores curtos.

    À esquerda, o mês: data-com, valor, Rend. % (2 casas) e pagamento. À direita de um
    divisor, o último rendimento antes do do mês. O que não houver vira traço. Quem não
    distribui nada (ex.: BOVA11) fica numa tabela no fim, com a cotação e a variação do
    dia. Abaixo de `COMPACT_WIDE`
    colunas, a parte do último vai para uma tabela logo abaixo. Os valores completos
    ficam em `--completo`, `--detalhes` e `--json`.
    """
    month_start = today.replace(day=1)
    side_by_side = width >= COMPACT_WIDE
    provisional = False
    no_dividends: list[AssetView] = []
    # Primeiro as linhas de todos os grupos, para as colunas terem a mesma largura em todos.
    sections: list[tuple[str | None, list[tuple[list[Text], list[Text]]]]] = []
    for title, members in groups:
        rows = []
        for view in members:
            snap = view.valid
            ticker = Text(view.ticker, style="ticker")
            if snap is not None and snap.datacom is None:
                no_dividends.append(view)
                continue
            if snap is None:
                # Sem dados: só traços.
                rows.append(([ticker, *dashes(4)], dashes(3)))
                continue
            if snap.datacom >= month_start:
                upcoming = snap.datacom >= today
                pct = short_percent(snap.rendimento_pct, snap.cotacao_provisoria)
                provisional = provisional or (snap.cotacao_provisoria and bool(pct))
                payment = snap.data_pagamento
                month_cells = [
                    ticker,
                    Text(short_date(snap.datacom, today), "datacom" if upcoming else "muted"),
                    Text(rendimento_short(snap)),
                    Text(pct or DASH),
                    Text(short_date(payment, today) if payment else DASH, "muted"),
                ]
                datacom, valor = snap.datacom_anterior, snap.rendimento_anterior
                previous_pct = short_percent(snap.rendimento_pct_anterior)
            else:
                # O rendimento do mês ainda não saiu.
                month_cells = [ticker, *dashes(4)]
                datacom, valor = snap.datacom, snap.rendimento
                previous_pct = short_percent(snap.rendimento_pct, snap.cotacao_provisoria)
                provisional = provisional or (snap.cotacao_provisoria and bool(previous_pct))
            last_cells = [
                Text(short_date(datacom, today) if datacom else DASH, "muted"),
                Text(short_brl(valor) if datacom else DASH, "muted"),
                Text(previous_pct if datacom and previous_pct else DASH, "muted"),
            ]
            rows.append((month_cells, last_cells))
        if rows:
            sections.append((title, rows))

    month_headers = ["Ativo", "Data-com", "Rendimento", "Rend. %", "Pagamento"]
    last_headers = ["Último", "Rendimento", "Rend. %"]

    def widths(headers: list[str], index: int) -> list[int]:
        cells = [row[index] for _, rows in sections for row in rows]
        return [max([len(h), *(c[i].cell_len for c in cells)]) for i, h in enumerate(headers)]

    month_w, last_w = widths(month_headers, 0), widths(last_headers, 1)
    ticker_w = month_w[0]

    parts: list[RenderableType] = []
    for title, rows in sections:
        month = _plain(*month_headers)
        ticker_column = [] if side_by_side else ["Ativo"]
        last = _plain(*ticker_column, *last_headers)
        for column, w in zip(month.columns, month_w, strict=True):
            column.min_width = w
        for column, w in zip(
            last.columns, ([ticker_w] if ticker_column else []) + last_w, strict=True
        ):
            column.min_width = w
        for column in (month.columns[3], last.columns[-1]):
            column.justify = "right"
        for month_cells, last_cells in rows:
            month.add_row(*month_cells)
            last.add_row(*([month_cells[0]] if ticker_column else []), *last_cells)
        if parts:
            parts.append(Text(""))
        if title:
            parts.append(Text(title, style="bold"))
        if side_by_side:
            # Divisor entre o mês e o último; cruza a linha abaixo do cabeçalho.
            divider = Text("\n".join(["  │  ", "──┼──", *["  │  "] * len(rows)]), style="border")
            grid = Table.grid()
            grid.add_row(month, divider, last)
            parts.append(grid)
        else:
            parts.extend([month, Text(""), last])

    if no_dividends:
        if parts:
            parts.append(Text(""))
        parts.append(Text("Sem proventos", style="bold"))
        parts.append(price_table(no_dividends))
    if provisional:
        parts.append(Text(f"\n{PROVISIONAL_NOTE}", style="muted"))
    return Padding(Group(*parts), (0, 0, 0, INDENT), expand=False)


def price_table(views: list[AssetView]) -> Table:
    """Cotação e variação do dia, da maior alta para a maior queda."""

    def change(view: AssetView) -> Decimal:
        value = view.valid.variacao_dia if view.valid else None
        return value if value is not None else Decimal("-Infinity")

    table = _plain("Ativo", "Cotação", "Dia")
    table.columns[2].justify = "right"
    for view in sorted(views, key=lambda v: (-change(v), v.ticker)):
        snap = view.valid
        price = snap.cotacao_atual if snap else None
        table.add_row(
            Text(view.ticker, style="ticker"),
            format_brl(price) if price is not None else DASH,
            change_text(snap.variacao_dia if snap else None),
        )
    return table


def change_text(value: Decimal | None) -> Text:
    """▲ 0,85% em verde, ▼ 0,32% em vermelho, 0,00% apagado."""
    if value is None:
        return Text(DASH, "muted")
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format_percent(abs(rounded))
    if rounded > 0:
        return Text(f"▲ {text}", "ok")
    if rounded < 0:
        return Text(f"▼ {text}", "fail")
    return Text(text, "muted")


def dashes(count: int) -> list[Text]:
    return [Text(DASH, "muted") for _ in range(count)]


def rendimento_short(snap) -> str:
    if snap is not None and snap.rendimento is None and snap.datacom is not None:
        return UNDECLARED
    return short_brl(snap.rendimento if snap else None)


UNDECLARED = "a definir"


def rendimento_text(snap) -> str:
    """Valor por cota; "a definir" quando a data-com já foi divulgada e o valor não."""
    if snap is not None and snap.rendimento is None and snap.datacom is not None:
        return UNDECLARED
    return format_brl(snap.rendimento if snap else None)


def dash_or(fmt, value) -> str:
    return fmt(value) if value is not None else DASH


def marked(fmt, value, provisional: bool) -> str:
    if value is None:
        return DASH
    return f"{fmt(value)}*" if provisional else fmt(value)


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
                    rendimento_text(snap),
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
    grid.add_row("Tipo", view.asset_type.value)
    grid.add_row("Data-com", Text(format_date(snap.datacom if snap else None), style="datacom"))
    grid.add_row("Rendimento por cota", rendimento_text(snap))
    base = format_brl(snap.cotacao_base if snap else None)
    if snap and snap.cotacao_provisoria:
        base += " (provisória: o fechamento oficial da B3 sai na manhã seguinte)"
    grid.add_row("Cotação-base", base)
    grid.add_row("Rend. %", format_percent(snap.rendimento_pct if snap else None))
    grid.add_row("Data de pagamento", format_date(snap.data_pagamento if snap else None))
    if snap and snap.agenda:
        grid.add_row("Próximas datas-com", ", ".join(format_date(d) for d in snap.agenda))
    grid.add_row("", "")
    grid.add_row("Data-com anterior", format_date(snap.datacom_anterior if snap else None))
    grid.add_row("Rendimento anterior", format_brl(snap.rendimento_anterior if snap else None))
    grid.add_row("Cotação-base anterior", format_brl(snap.cotacao_base_anterior if snap else None))
    grid.add_row("Rend. % anterior", format_percent(snap.rendimento_pct_anterior if snap else None))
    grid.add_row("", "")
    grid.add_row("Última consulta válida", format_datetime(snap.fetched_at if snap else None))
    if view.asset_type == AssetType.ETF:
        origin = config.ETF_SOURCE_NAME
        if snap and snap.agenda:
            origin += " e agenda da gestora"
    else:
        origin = config.SOURCE_NAME
        if snap and snap.source_field:
            origin += f", {snap.source_field}"
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
