"""Entradas do usuário: prompt_toolkit quando disponível, input() como alternativa."""

import contextlib
import os
import sys
from collections.abc import Callable

from rich.console import Console, Group, RenderableType
from rich.text import Text

from ativos_cli.ui.tables import key_hints
from ativos_cli.ui.theme import render_ansi


def is_interactive() -> bool:
    if os.environ.get("ATIVOS_NO_INPUT"):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _read_key_fallback(keys: set[str]) -> str | None:
    try:
        answer = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    return answer[:1] if answer[:1] in keys else None


def menu(
    console: Console,
    render: Callable[[int, int], RenderableType],
    count: int,
    keys: dict[str, str],
    selected: int = 0,
) -> tuple[str, int] | None:
    """Menu navegável com ↑/↓ (ou j/k). Devolve (ação, índice) ou None se cancelado.

    `render(selected, width)` monta o conteúdo; `keys` liga teclas a ações. Esc, Q e
    Ctrl+C cancelam. Sem suporte à captura de teclas, levanta a exceção original para
    quem chama usar a alternativa textual.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    state = {"selected": min(max(selected, 0), max(count - 1, 0))}

    def draw():
        width = app.output.get_size().columns if app.is_running else console.width
        return ANSI(render_ansi(console, render(state["selected"], width), width))

    bindings = KeyBindings()

    @bindings.add("up")
    @bindings.add("k")
    @bindings.add("s-tab")
    def _up(event) -> None:
        state["selected"] = (state["selected"] - 1) % max(count, 1)

    @bindings.add("down")
    @bindings.add("j")
    @bindings.add("tab")
    def _down(event) -> None:
        state["selected"] = (state["selected"] + 1) % max(count, 1)

    for digit in range(1, min(count, 9) + 1):
        bindings.add(str(digit))(lambda event, i=digit - 1: state.update(selected=i))

    def bind(key: str, action: str) -> None:
        def handler(event) -> None:
            event.app.exit(result=(action, state["selected"]))

        for variant in {key, key.upper()} if len(key) == 1 else {key}:
            bindings.add(variant)(handler)

    for key, action in keys.items():
        bind(key, action)

    @bindings.add("escape", eager=True)
    @bindings.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    if "q" not in keys:
        bindings.add("q")(_cancel)
        bindings.add("Q")(_cancel)

    app = Application(
        layout=Layout(Window(FormattedTextControl(draw, show_cursor=False))),
        key_bindings=bindings,
        full_screen=False,
        erase_when_done=True,
    )
    return app.run()


def option_list(options: list[str], selected: int) -> Group:
    lines = []
    for i, label in enumerate(options):
        if i == selected:
            lines.append(Text(f"  ❯ {label}", style="key"))
        else:
            lines.append(Text(f"    {label}"))
    return Group(*lines)


def confirm(console: Console, question: str, default: bool = False) -> bool:
    """Pergunta Sim/Não com seleção por setas. S/N também respondem direto."""
    options = ["Sim", "Não"]

    def render(selected: int, width: int) -> RenderableType:
        return Group(
            Text(),
            Text(f"  {question}"),
            Text(),
            option_list(options, selected),
            Text(),
            key_hints([("↑/↓", "Navegar"), ("Enter", "Confirmar"), ("Esc", "Cancelar")]),
        )

    try:
        result = menu(
            console,
            render,
            len(options),
            {"enter": "pick", "s": "yes", "y": "yes", "n": "no"},
            selected=0 if default else 1,
        )
    except Exception:
        return _confirm_fallback(console, question, default)

    if result is None:
        answer = False
    else:
        action, index = result
        answer = action == "yes" or (action == "pick" and index == 0)
    line = Text(f"  {question} ")
    line.append("Sim" if answer else "Não", style="key")
    console.print()
    console.print(line)
    return answer


def _confirm_fallback(console: Console, question: str, default: bool) -> bool:
    console.print()
    console.print(Text(f"  {question}"))
    console.print()
    console.print(key_hints([("S", "Sim"), ("N", "Não")]))
    answer = _read_key_fallback({"s", "n", "y"})
    if answer is None:
        return default
    return answer in {"s", "y"}


def ask_text(console: Console, label: str) -> str | None:
    """Pergunta um texto. Esc ou Ctrl+C cancelam (retorna None)."""
    try:
        from prompt_toolkit import prompt
        from prompt_toolkit.key_binding import KeyBindings

        bindings = KeyBindings()

        @bindings.add("escape", eager=True)
        def _cancel(event) -> None:
            event.app.exit(result=None)

        answer = prompt(f"  {label}: ", key_bindings=bindings)
    except (EOFError, KeyboardInterrupt):
        return None
    except Exception:
        try:
            answer = input(f"  {label}: ")
        except (EOFError, KeyboardInterrupt):
            return None
    if answer is None:
        return None
    return answer.strip() or None


def show_and_wait(console: Console, renderable, footer: str = "Pressione qualquer tecla") -> None:
    """Mostra um conteúdo temporário até o usuário pressionar uma tecla."""
    content = Group(renderable, Text(), Text(f"  {footer}", style="muted"))
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.keys import Keys
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.controls import FormattedTextControl

        bindings = KeyBindings()
        for key in (Keys.Any, "enter", "escape", "c-c", "up", "down", "left", "right", "tab"):
            bindings.add(key, eager=key == "escape")(lambda event: event.app.exit())

        ansi = ANSI(render_ansi(console, content, console.width))
        Application(
            layout=Layout(Window(FormattedTextControl(ansi, show_cursor=False))),
            key_bindings=bindings,
            full_screen=False,
            erase_when_done=True,
        ).run()
    except Exception:
        console.print(content)
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input()
