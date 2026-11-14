import json
from datetime import date
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from ativos_cli import __version__, cli
from ativos_cli.errors import FetchError
from ativos_cli.main import rewrite_args
from ativos_cli.models import AssetType, AssetView, DisplayStatus, FetchStatus, Snapshot
from ativos_cli.ui.tables import sort_by_datacom
from ativos_cli.ui.wallet import Action, parse_text_command
from ativos_cli.utils.dates import now_utc
from tests.conftest import failed_result


@pytest.fixture
def run(tmp_path, monkeypatch, fetcher):
    monkeypatch.setenv("ATIVOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATIVOS_NO_INPUT", "1")
    monkeypatch.setattr(cli, "build_fetcher", lambda debug: fetcher)
    # As fixtures têm data-com em 30/09/2026: fixa "hoje" nesse mês.
    monkeypatch.setattr(cli, "today", lambda: date(2026, 9, 30))
    runner = CliRunner()

    def invoke(*args, width=100):
        return runner.invoke(
            cli.app, rewrite_args(list(args)), env={"COLUMNS": str(width), "NO_COLOR": "1"}
        )

    return invoke


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["MXRF11"], ["show", "MXRF11"]),
        (["mxrf11"], ["show", "mxrf11"]),
        (["mxrf"], ["search", "mxrf"]),
        (["maxi", "renda"], ["search", "maxi", "renda"]),
        (["--debug", "MXRF11", "--json"], ["--debug", "show", "MXRF11", "--json"]),
        (["search", "maxi"], ["search", "maxi"]),
        ([], []),
        (["--help"], ["--help"]),
    ],
)
def test_rewrite_args(args, expected):
    assert rewrite_args(args) == expected


def test_version(run):
    result = run("--version")
    assert __version__ in result.output


def test_help_lists_commands(run):
    result = run("--help")
    assert result.exit_code == 0
    for command in ("search", "add", "remove", "refresh"):
        assert command in result.output


def test_show_one_row_table(run):
    result = run("MXRF11", "--completo")
    assert result.exit_code == 0, result.output
    assert "Maxi Renda" not in result.output
    assert "30/09/2026" in result.output
    assert "R$ 0,10" in result.output
    assert "R$ 9,17" in result.output
    assert "1,0905%" in result.output
    assert "CONSULTA" not in result.output
    # Uma linha na tabela do mês e outra na do rendimento anterior, logo abaixo.
    rows = [line for line in result.output.splitlines() if "MXRF11" in line]
    assert len(rows) == 2
    assert "R$ 9,17" in rows[0]


def test_previous_month_datacom_shows_dashes(run, monkeypatch):
    monkeypatch.setattr(cli, "today", lambda: date(2026, 10, 1))
    result = run("MXRF11", "--completo")
    assert result.exit_code == 0, result.output
    month, previous = [line for line in result.output.splitlines() if "MXRF11" in line]
    assert month.split() == ["MXRF11", "—", "—", "—", "—", "—"]
    assert previous.split() == ["MXRF11", "30/09/2026", "R$", "0,10", "1,0905%"]


def test_wide_terminal_shows_previous_dividend(run):
    result = run("MXRF11", "--completo", width=130)
    assert result.exit_code == 0, result.output
    header = next(line for line in result.output.splitlines() if "Ativo" in line)
    month, previous = header.split("│")
    assert month.split()[-1] == "Pagamento"
    assert [c.strip() for c in previous.split("   ")] == [
        "Data-com ant.",
        "Rend. ant.",
        "Rend. % ant.",
    ]
    assert "┼" in result.output
    row = next(line for line in result.output.splitlines() if "MXRF11" in line)
    assert row.split()[-6:] == ["15/10/2026", "│", "29/08/2026", "R$", "0,09", "0,9836%"]


def test_narrow_terminal_stacks_previous_dividend(run):
    result = run("MXRF11", "--completo", width=80)
    assert result.exit_code == 0, result.output
    assert "│" not in result.output
    lines = result.output.splitlines()
    assert max(len(line) for line in lines) <= 80
    month, previous = [line for line in lines if "MXRF11" in line]
    assert month.split()[-1] == "15/10/2026"  # Pagamento junto do mês
    assert previous.split() == ["MXRF11", "29/08/2026", "R$", "0,09", "0,9836%"]
    assert "Data-com ant." in result.output


def test_previous_month_datacom_becomes_previous(run, monkeypatch):
    monkeypatch.setattr(cli, "today", lambda: date(2026, 10, 1))
    result = run("MXRF11", "--completo", width=130)
    row = next(line for line in result.output.splitlines() if "MXRF11" in line)
    assert row.split() == [
        *["MXRF11", "—", "—", "—", "—", "—"],
        *["│", "30/09/2026", "R$", "0,10", "1,0905%"],
    ]


def test_provisional_price_is_marked(run, fetcher):
    fetcher.results["MXRF11"].data.cotacao_provisoria = True
    assert "1,09%*" in run("MXRF11").output
    result = run("MXRF11", "--completo")
    assert "R$ 9,17*" in result.output
    assert "1,0905%*" in result.output
    assert "cotação provisória" in result.output
    assert run("MXRF11", "--json").output.count('"cotacao_provisoria": true') == 1


def test_official_price_has_no_mark(run):
    result = run("MXRF11")
    assert "*" not in result.output
    assert "provisória" not in result.output


def test_show_json(run):
    result = run("MXRF11", "--json")
    data = json.loads(result.output)
    assert data["datacom"] == "2026-09-30"
    assert data["rendimento"] == "0.1"
    assert data["rendimento_pct"] == "1.0905"
    assert data["datacom_anterior"] == "2026-08-29"
    assert data["rendimento_anterior"] == "0.09"
    assert data["rendimento_pct_anterior"] == "0.9836"
    assert data["cotacao_base_anterior"] == "9.15"
    assert data["status"] == "updated"


def test_show_invalid_ticker(run):
    result = run("show", "ABC")
    assert result.exit_code == 1
    assert "Ticker inválido" in result.output


def test_partial_ticker_searches(run):
    result = run("mxrf")
    assert result.exit_code == 0
    assert "MXRF11" in result.output


def test_show_not_found(run):
    result = run("ZZZZ11")
    assert result.exit_code == 1
    assert "não encontrado" in result.output


def test_show_cached_after_failure(run, fetcher):
    run("MXRF11")
    fetcher.results["MXRF11"] = failed_result("MXRF11")
    result = run("MXRF11")
    assert result.exit_code == 0
    assert "Não foi possível atualizar" in result.output
    assert "R$ 0,10" in result.output


def test_show_details(run):
    result = run("MXRF11", "--detalhes")
    assert "Origem dos dados" in result.output
    assert "fiis.com.br" in result.output


def test_add_remove_flow(run):
    assert "adicionado" in run("add", "MXRF11").output
    assert "já está" in run("add", "mxrf11").output
    assert "removido" in run("remove", "MXRF11").output
    result = run("remove", "MXRF11")
    assert result.exit_code == 1
    assert "não está na carteira" in result.output


def test_purge_requires_yes_without_terminal(run):
    run("add", "MXRF11")
    assert run("remove", "MXRF11", "--purge").exit_code == 1
    assert run("remove", "MXRF11", "--purge", "--yes").exit_code == 0
    assert "Nenhuma consulta" in run("history", "MXRF11").output


def test_wallet_single_table(run):
    run("add", "MXRF11")
    run("add", "KNCR11")
    result = run("--completo")
    assert result.exit_code == 0, result.output
    assert "MXRF11" in result.output
    assert "KNCR11" in result.output
    assert result.output.count("Cotação-base") == 1
    assert result.output.count("Data-com ant.") == 1


def test_wallet_sorted_by_datacom(run, fetcher):
    fetcher.set_data("HGLG11", name="CSHG Logística", datacom=date(2026, 9, 15))
    for ticker in ("MXRF11", "HGLG11", "KNCR11"):
        run("add", ticker)
    fetcher.results["MXRF11"].data.datacom = date(2026, 9, 29)
    result = run()
    month = [line.split()[0] for line in result.output.splitlines() if "11 " in line][:3]
    # 15/09 (HGLG11), 29/09 (MXRF11), 30/09 (KNCR11).
    assert month == ["HGLG11", "MXRF11", "KNCR11"]
    assert "ETFs" not in result.output


def test_wallet_lists_etfs_apart(run, fetcher):
    fetcher.set_data(
        "NDIV11",
        name="Nu Renda Ibov Smart Dividendos",
        asset_type=AssetType.ETF,
        datacom=date(2026, 9, 8),
        rendimento=Decimal("1.1605589"),
        cotacao_base=Decimal("11.2"),
        rendimento_pct=Decimal("10.3621"),
        data_pagamento=date(2026, 9, 15),
    )
    run("add", "MXRF11")
    run("add", "NDIV11")
    result = run()
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    titles = [line.split()[0] for line in lines if line.split()[:1] in (["FIIs"], ["ETFs"])]
    assert titles == ["FIIs", "ETFs"]
    etfs_at = next(i for i, line in enumerate(lines) if line.split()[:1] == ["ETFs"])
    assert all("NDIV11" not in line for line in lines[:etfs_at])
    assert all("MXRF11" not in line for line in lines[etfs_at:])
    assert "R$ 1,1606" in result.output
    assert "R$ 1,1605589" in run("--completo").output
    assert run("--completo").output.count("Cotação-base") == 2
    data = json.loads(run("refresh", "--json").output)
    assert {d["ticker"]: d["tipo"] for d in data} == {"MXRF11": "FII", "NDIV11": "ETF"}


def test_undeclared_dividend(run, fetcher):
    fetcher.set_data(
        "QQQI11",
        asset_type=AssetType.ETF,
        datacom=date(2026, 9, 29),
        data_pagamento=date(2026, 10, 8),
        datacom_anterior=date(2026, 8, 18),
        rendimento_anterior=Decimal("1.1583761"),
        agenda=[date(2026, 9, 29), date(2026, 10, 20)],
    )
    result = run("QQQI11", "--detalhes")
    month = next(line for line in result.output.splitlines() if line.startswith("  QQQI11"))
    assert month.split() == [
        *["QQQI11", "29/09", "a", "definir", "—", "08/10"],
        *["│", "18/08", "R$", "1,1584", "—"],
    ]
    assert "Próximas datas-com" in result.output
    assert "29/09/2026, 20/10/2026" in result.output
    assert json.loads(run("QQQI11", "--json").output)["agenda"] == ["2026-09-29", "2026-10-20"]


def test_wallet_marks_failures(run, fetcher):
    run("add", "MXRF11")
    run("add", "KNCR11")
    fetcher.results["KNCR11"] = failed_result("KNCR11")
    result = run()
    assert "KNCR11: Tempo esgotado" in result.output
    assert "R$ 1,13" in result.output  # o último dado válido do KNCR11


def test_wallet_empty(run):
    result = run()
    assert "vazia" in result.output


def test_narrow_terminal_keeps_priority_columns(run):
    run("add", "MXRF11")
    result = run("--completo", width=60)
    assert "Data-com" in result.output
    assert "Cotação-base" in result.output
    assert "Pagamento" not in result.output
    assert all(len(line) <= 60 for line in result.output.splitlines())


def test_refresh_exit_code(run, fetcher):
    run("add", "MXRF11")
    assert run("refresh").exit_code == 0
    fetcher.results["MXRF11"] = failed_result("MXRF11")
    result = run("refresh")
    assert result.exit_code == 1
    assert "MXRF11: Tempo esgotado" in result.output


def test_refresh_json(run):
    run("add", "MXRF11")
    data = json.loads(run("refresh", "--json").output)
    assert [d["ticker"] for d in data] == ["MXRF11"]


def test_search_fetches_site_every_time(run, fetcher):
    result = run("search", "maxi", "renda")
    assert "MXRF11" in result.output
    assert fetcher.catalog_calls == 1
    run("search", "kncr")
    assert fetcher.catalog_calls == 2


def test_search_falls_back_to_saved_catalog(run, fetcher):
    run("search", "maxi")
    fetcher.catalog_error = FetchError("Tempo esgotado ao consultar o site.")
    result = run("search", "maxi", "renda")
    assert "Usando a lista salva" in result.output
    assert "MXRF11" in result.output


def test_search_offline_without_saved_catalog(run, fetcher):
    fetcher.catalog_error = FetchError("Falha de conexão.")
    result = run("search", "MXRF11")
    assert "Não foi possível pesquisar" in result.output


def test_search(run):
    result = run("search", "maxi", "renda")
    assert "MXRF11" in result.output
    assert "30/09" in result.output
    assert "Data-com" in run("search", "maxi", "renda", "--completo").output
    data = json.loads(run("search", "kncr", "--json").output)
    assert data[0]["ticker"] == "KNCR11"
    assert data[0]["datacom"]


def test_catalog_status(run):
    assert "vazio" in run("catalog", "status").output
    run("catalog", "update")
    assert "ativos, atualizado em" in run("catalog", "status").output


def test_history(run, fetcher):
    run("MXRF11")
    fetcher.results["MXRF11"] = failed_result("MXRF11")
    run("MXRF11")
    result = run("history", "MXRF11")
    assert "Sucesso" in result.output
    assert "Tempo esgotado" in result.output


@pytest.mark.parametrize(
    ("raw", "action", "index"),
    [
        ("q", Action.QUIT, 0),
        ("a", Action.ADD, 0),
        ("d 2", Action.DETAILS, 1),
        ("r 1", Action.REMOVE, 0),
    ],
)
def test_text_menu_commands(raw, action, index):
    choice = parse_text_command(raw, count=2)
    assert (choice.action, choice.index) == (action, index)


@pytest.mark.parametrize("raw", ["", "x", "d", "d 9", "r abc"])
def test_text_menu_invalid(raw):
    assert parse_text_command(raw, count=2) is None


def test_compact_wallet(run, fetcher, monkeypatch):
    """Visão padrão: mês no topo, colunas com cabeçalho, datas e valores curtos."""
    monkeypatch.setattr(cli, "today", lambda: date(2026, 10, 1))
    fetcher.set_data(
        "NDIV11",
        asset_type=AssetType.ETF,
        datacom=date(2026, 10, 8),
        rendimento=Decimal("0.1916249"),
        rendimento_pct=Decimal("0.1634"),
        data_pagamento=date(2026, 10, 15),
    )
    fetcher.set_data(
        "BOVA11", asset_type=AssetType.ETF, cotacao_atual=Decimal("169.99"),
        variacao_dia=Decimal("0.8543459"),
    )  # fmt: skip
    fetcher.set_data(
        "IVVB11", asset_type=AssetType.ETF, cotacao_atual=Decimal("380.1"),
        variacao_dia=Decimal("-0.321"),
    )  # fmt: skip
    for ticker in ("MXRF11", "NDIV11", "IVVB11", "BOVA11"):
        run("add", ticker)
    result = run()
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines[0].strip() == "Outubro/2026"
    assert "Cotação-base" not in result.output
    header = next(line for line in lines if "Data-com" in line)
    assert header.split() == [
        *["Ativo", "Data-com", "Rendimento", "Rend.", "%", "Pagamento"],
        *["│", "Último", "Rendimento", "Rend.", "%"],
    ]
    mxrf = next(line for line in lines if "MXRF11" in line)
    # Rendimento do mês ainda não saiu: traços no mês, o último à direita.
    assert mxrf.split() == [*["MXRF11", "—", "—", "—", "—"], *["│", "30/09", "R$", "0,10", "1,09%"]]
    ndiv = next(line for line in lines if "NDIV11" in line)
    assert ndiv.split() == [
        *["NDIV11", "08/10", "R$", "0,1916", "0,16%", "15/10"],
        *["│", "—"],
        "—",
        "—",
    ]
    # FIIs e ETFs com as colunas alinhadas: o divisor fica na mesma posição.
    columns = {line.index("│") for line in lines if "│" in line}
    assert len(columns) == 1
    # ETFs que não distribuem: tabela própria no fim, da maior alta para a maior queda.
    at = next(i for i, line in enumerate(lines) if line.strip() == "Sem proventos")
    assert lines[at + 1].split() == ["Ativo", "Cotação", "Dia"]
    assert lines[at + 3].split() == ["BOVA11", "R$", "169,99", "▲", "0,85%"]
    assert lines[at + 4].split() == ["IVVB11", "R$", "380,10", "▼", "0,32%"]
    assert all("BOVA11" not in line for line in lines[:at])
    data = {d["ticker"]: d for d in json.loads(run("refresh", "--json").output)}
    assert data["BOVA11"]["variacao_dia"] == "0.8543459"
    assert data["BOVA11"]["cotacao_atual"] == "169.99"

    # Terminal estreito: o último rendimento vai para uma tabela logo abaixo.
    narrow = run(width=60).output
    assert "│" not in narrow.replace("─", "")
    assert ["MXRF11", "30/09", "R$", "0,10", "1,09%"] in [
        line.split() for line in narrow.splitlines()
    ]
    assert all(len(line) <= 60 for line in narrow.splitlines())


def test_sort_month_datacoms_first_oldest_to_newest():
    def view(ticker: str, datacom: date | None) -> AssetView:
        snap = Snapshot(
            id=1,
            ticker=ticker,
            status=FetchStatus.OK,
            source_url="",
            fetched_at=now_utc(),
            datacom=datacom,
        )
        return AssetView(ticker=ticker, status=DisplayStatus.UPDATED, valid=snap)

    views = [
        view("OUTU11", date(2026, 10, 30)),
        view("SEMD11", None),
        view("DEZE11", date(2026, 12, 1)),
        view("ONTE11", date(2026, 11, 11)),
        view("AMAN11", date(2026, 11, 13)),
        view("HOJE11", date(2026, 11, 12)),
    ]
    ordered = [v.ticker for v in sort_by_datacom(views, date(2026, 11, 12))]
    # As do mês e depois, da mais antiga para a mais nova; depois as de meses anteriores
    # (linha do mês com traços); por fim quem não tem data-com.
    assert ordered == ["ONTE11", "HOJE11", "AMAN11", "DEZE11", "OUTU11", "SEMD11"]
