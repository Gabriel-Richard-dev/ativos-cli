"""Tela interativa da carteira (prompt_toolkit) e alternativa textual."""

from dataclasses import dataclass
from enum import StrEnum

from rich.console import Console, Group, RenderableType
from rich.text import Text

from ativos_cli.models import AssetView, DisplayStatus
from ativos_cli.ui.tables import assets_table, header, key_hints
from ativos_cli.ui.theme import render_ansi


class Action(StrEnum):
    DETAILS = "details"
    ADD = "add"
    REMOVE = "remove"
    REFRESH = "refresh"
    SEARCH = "search"
    QUIT = "quit"


@dataclass
class Choice:
    action: Action
    index: int = 0


HINTS = (
    [("↑/↓", "Navegar"), ("Enter", "Detalhes"), ("A", "Adicionar"), ("R", "Remover")],
    [("/", "Pesquisar"), ("U", "Atualizar"), ("Q", "Sair")],
)
TEXT_HINTS = (
    [("d N", "Detalhes"), ("a", "Adicionar"), ("r N", "Remover")],
    [("/", "Pesquisar"), ("u", "Atualizar"), ("q", "Sair")],
)


def summary_line(views: list[AssetView], refresh_label: str) -> Text:
    line = Text("  ")
    line.append("Ativos: ", style="muted")
    line.append(str(len(views)))
    line.append("     Atualização: ", style="muted")
    failed = sum(1 for v in views if v.last_error or v.status == DisplayStatus.FAILED)
    line.append(refresh_label, style="fail" if failed else None)
    return line


def wallet_renderable(
    views: list[AssetView],
    width: int,
    selected: int | None,
    refresh_label: str,
    message: Text | None,
    hints: tuple = HINTS,
    numbered: bool = False,
) -> RenderableType:
    parts: list[RenderableType] = [
        header("MINHA CARTEIRA", "Acompanhamento de rendimentos e datas-com", width),
        Text(),
        summary_line(views, refresh_label),
        Text(),
        assets_table(views, width, selected=selected, numbered=numbered),
        Text(),
    ]
    if message is not None:
        parts += [message, Text()]
    parts.append(key_hints(*hints))
    return Group(*parts)


class WalletScreen:
    """Renderiza a carteira com Rich dentro de uma aplicação prompt_toolkit.

    A tela retorna a ação escolhida; quem chama executa a ação e reabre a tela.
    """

    def __init__(self, console: Console) -> None:
        self.console = console

    def run(
        self,
        views: list[AssetView],
        selected: int,
        refresh_label: str,
        message: Text | None = None,
    ) -> Choice:
        from prompt_toolkit.application import Application
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.controls import FormattedTextControl

        state = {"selected": min(selected, max(len(views) - 1, 0))}

        def render():
            width = app.output.get_size().columns if app.is_running else self.console.width
            content = wallet_renderable(views, width, state["selected"], refresh_label, message)
            return ANSI(render_ansi(self.console, content, width))

        bindings = KeyBindings()

        @bindings.add("up")
        @bindings.add("k")
        def _up(event) -> None:
            state["selected"] = max(0, state["selected"] - 1)

        @bindings.add("down")
        @bindings.add("j")
        def _down(event) -> None:
            state["selected"] = min(len(views) - 1, state["selected"] + 1)

        def bind(keys: tuple[str, ...], action: Action, needs_row: bool = False) -> None:
            def handler(event) -> None:
                if needs_row and not views:
                    return
                event.app.exit(result=Choice(action, state["selected"]))

            for key in keys:
                bindings.add(key, eager=key == "escape")(handler)

        bind(("enter",), Action.DETAILS, needs_row=True)
        bind(("a", "A"), Action.ADD)
        bind(("r", "R", "delete"), Action.REMOVE, needs_row=True)
        bind(("u", "U"), Action.REFRESH)
        bind(("/",), Action.SEARCH)
        bind(("q", "Q", "escape", "c-c"), Action.QUIT)

        app = Application(
            layout=Layout(Window(FormattedTextControl(render, show_cursor=False))),
            key_bindings=bindings,
            full_screen=False,
            erase_when_done=True,
        )
        return app.run()


def parse_text_command(raw: str, count: int) -> Choice | None:
    """Alternativa textual: "d 2", "r 1", "a", "u", "/", "q"."""
    parts = raw.strip().lower().split()
    if not parts:
        return None
    command, arg = parts[0], parts[1] if len(parts) > 1 else None
    simple = {"a": Action.ADD, "u": Action.REFRESH, "/": Action.SEARCH, "q": Action.QUIT}
    if command in simple:
        return Choice(simple[command])
    if command in {"d", "r"} and arg and arg.isdigit() and 1 <= int(arg) <= count:
        return Choice(Action.DETAILS if command == "d" else Action.REMOVE, int(arg) - 1)
    return None
