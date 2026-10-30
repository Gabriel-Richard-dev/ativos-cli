"""Interface em tela cheia, sem terminal: lógica de abas, busca e ações."""

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import fragment_list_to_text, split_lines, to_formatted_text
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.output import DummyOutput

from ativos_cli.models import DisplayStatus
from ativos_cli.ui.app import AtivosApp, Mode
from ativos_cli.ui.tables import ADD_BUTTON
from ativos_cli.ui.theme import make_console
from tests.conftest import failed_result


@pytest.fixture
def make_app(service, search):
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):

        def build(**kwargs) -> AtivosApp:
            app = AtivosApp(service, search, make_console(), **kwargs)
            app.submit = lambda label, fn: fn()  # executa as operações na hora
            app.quote_delay = 0
            app._load_initial()
            return app

        yield build


def body(app: AtivosApp) -> str:
    return fragment_list_to_text(to_formatted_text(app._body()))


def test_empty_wallet_hint(make_app):
    app = make_app()
    assert "carteira está vazia" in body(app)


def test_wallet_is_refreshed_on_open(make_app, service):
    service.repo.add_to_wallet("MXRF11")
    app = make_app()
    assert [v.status for v in app.wallet] == [DisplayStatus.UPDATED]
    assert app.refresh_label == "concluída"
    assert "30/09/2026" in body(app)


def test_live_search_and_add(make_app, search):
    search.update_catalog()
    app = make_app()
    app.search_buffer.text = "maxi renda"
    assert app.searching
    assert app.hits[0].entry.ticker == "MXRF11"
    assert "Maxi Renda" in body(app)
    assert "30/09/2026" in body(app)  # data-base consultada no site para os resultados

    app.open_details()
    assert app.mode == Mode.DETAILS
    assert app.details.ticker == "MXRF11"
    app.add_current()
    assert [v.ticker for v in app.wallet] == ["MXRF11"]
    assert app.message == ("ok", "MXRF11 adicionado à carteira.")


def click(app: AtivosApp, text: str, line_with: str) -> None:
    """Clica no início de `text` na linha que contém `line_with`."""
    for line in split_lines(app._body()):
        content = "".join(f[1] for f in line)
        if line_with not in content or text not in content:
            continue
        col, pos = content.index(text), 0
        for fragment in line:
            if pos <= col < pos + len(fragment[1]):
                assert len(fragment) > 2, f"{text!r} não é clicável"
                event = MouseEvent(
                    Point(0, 0), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset()
                )
                fragment[2](event)
                return
            pos += len(fragment[1])
    raise AssertionError(f"{text!r} não encontrado na linha de {line_with}")


def test_add_button_in_search_results(make_app, search):
    search.update_catalog()
    app = make_app()
    app.search_buffer.text = "maxi renda"
    assert ADD_BUTTON in body(app)
    click(app, ADD_BUTTON, "MXRF11")
    assert [v.ticker for v in app.wallet] == ["MXRF11"]
    assert app.message == ("ok", "MXRF11 adicionado à carteira.")
    assert "Na carteira" in body(app)


def test_click_selects_then_opens_row(make_app, search):
    search.update_catalog()
    app = make_app()
    app.search_buffer.text = "maxi"
    assert app.hits[0].entry.ticker == "MXRF11"
    second = app.hits[1].entry.ticker
    click(app, second, second)
    assert app.search_sel == 1
    click(app, "MXRF11", "MXRF11")
    assert app.search_sel == 0
    assert app.mode == Mode.LIST
    click(app, "MXRF11", "MXRF11")
    assert app.mode == Mode.DETAILS
    assert app.details.ticker == "MXRF11"


def test_search_prefilled_from_command(make_app, search):
    search.update_catalog()
    app = make_app(term="kncr")
    assert app.hits[0].entry.ticker == "KNCR11"


def test_clearing_search_shows_wallet_again(make_app, service, search):
    search.update_catalog()
    service.repo.add_to_wallet("KNCR11")
    app = make_app()
    app.search_buffer.text = "maxi"
    assert "Maxi Renda" in body(app)
    app.clear_search()
    assert not app.searching
    assert "KNCR11" in body(app)
    assert "Maxi Renda" not in body(app)


def test_remove_requires_confirmation(make_app, service):
    service.repo.add_to_wallet("MXRF11")
    service.repo.add_to_wallet("KNCR11")
    app = make_app()
    app.move(1)
    app.ask_remove()
    assert app.mode == Mode.CONFIRM
    assert "KNCR11" in app.confirmation.question
    app.answer(False)
    assert len(app.wallet) == 2
    app.ask_remove()
    app.answer(True)
    assert [v.ticker for v in app.wallet] == ["MXRF11"]
    assert app.mode == Mode.LIST


def test_refresh_failure_keeps_cache(make_app, service, fetcher):
    service.repo.add_to_wallet("MXRF11")
    app = make_app()
    fetcher.results["MXRF11"] = failed_result("MXRF11")
    app.refresh()
    view = app.wallet[0]
    assert view.status == DisplayStatus.CACHED
    assert view.last_error
    assert app.message[0] == "warn"
    assert "Falha" in body(app)


def test_selection_stays_in_bounds(make_app, service):
    service.repo.add_to_wallet("MXRF11")
    app = make_app()
    app.move(-5)
    assert app.wallet_sel == 0
    app.move(5)
    assert app.wallet_sel == 0
