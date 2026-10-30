import json

import pytest
from typer.testing import CliRunner

from ativos_cli import __version__, cli
from ativos_cli.errors import FetchError
from ativos_cli.main import rewrite_args
from ativos_cli.ui.wallet import Action, parse_text_command
from tests.conftest import failed_result


@pytest.fixture
def run(tmp_path, monkeypatch, fetcher):
    monkeypatch.setenv("ATIVOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATIVOS_NO_INPUT", "1")
    monkeypatch.setattr(cli, "build_fetcher", lambda debug: fetcher)
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
    result = run("MXRF11")
    assert result.exit_code == 0, result.output
    assert "Maxi Renda" not in result.output
    assert "30/09/2026" in result.output
    assert "R$ 0,10" in result.output
    assert "R$ 9,17" in result.output
    assert "1,09%" in result.output
    assert "CONSULTA" not in result.output
    rows = [line for line in result.output.splitlines() if "R$" in line]
    assert len(rows) == 1


def test_show_json(run):
    result = run("MXRF11", "--json")
    data = json.loads(result.output)
    assert data["datacom"] == "2026-09-30"
    assert data["rendimento"] == "0.1"
    assert data["rendimento_pct"].startswith("1.09")
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
    result = run()
    assert result.exit_code == 0, result.output
    assert "MXRF11" in result.output
    assert "KNCR11" in result.output
    assert result.output.count("Data-com") == 1


def test_wallet_marks_failures(run, fetcher):
    run("add", "MXRF11")
    run("add", "KNCR11")
    fetcher.results["KNCR11"] = failed_result("KNCR11")
    result = run()
    assert "KNCR11: Tempo esgotado" in result.output
    assert "R$ 106,40" in result.output


def test_wallet_empty(run):
    result = run()
    assert "vazia" in result.output


def test_narrow_terminal_keeps_priority_columns(run):
    run("add", "MXRF11")
    result = run(width=60)
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
    assert "Data-com" in result.output
    assert "30/09/2026" in result.output
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
