"""Tema visual único. Rich respeita NO_COLOR e terminais sem cor automaticamente."""

from io import StringIO

from rich.console import Console, RenderableType
from rich.theme import Theme

THEME = Theme(
    {
        "brand": "bold",
        "muted": "dim",
        "ticker": "bold",
        "datacom": "bold cyan",
        "value": "none",
        "key": "cyan",
        "ok": "green",
        "warn": "yellow",
        "fail": "red",
        "selected": "reverse",
        "button": "bold black on cyan",
        "border": "bright_black",
    }
)


def make_console(stderr: bool = False) -> Console:
    return Console(theme=THEME, highlight=False, stderr=stderr)


def render_ansi(console: Console, renderable: RenderableType, width: int) -> str:
    """Renderiza para texto ANSI (exibido pelo prompt_toolkit) com as capacidades do console."""
    buffer = StringIO()
    Console(
        file=buffer,
        theme=THEME,
        width=width,
        force_terminal=True,
        color_system=console.color_system or None,
        no_color=console.no_color,
        highlight=False,
    ).print(renderable, end="")
    return buffer.getvalue()
