"""Ponto de entrada do comando `ativos`."""

import sys

from ativos_cli.cli import app
from ativos_cli.scraper.parser import is_valid_ticker, normalize_ticker
from ativos_cli.scraper.runner import RUNNER_FLAG

COMMANDS = {"show", "search", "add", "remove", "refresh", "history", "catalog"}


def rewrite_args(args: list[str]) -> list[str]:
    """Atalhos: `ativos MXRF11` consulta o ativo; `ativos mxrf` ou `ativos maxi renda` pesquisa."""
    for i, arg in enumerate(args):
        if arg.startswith("-"):
            continue
        if arg in COMMANDS:
            return args
        command = "show" if is_valid_ticker(normalize_ticker(arg)) else "search"
        return [*args[:i], command, *args[i:]]
    return args


def run() -> None:
    if sys.argv[1:2] == [RUNNER_FLAG]:
        from ativos_cli.scraper.runner import main

        sys.exit(main(sys.argv[2:]))
    app(args=rewrite_args(sys.argv[1:]), prog_name="ativos")


if __name__ == "__main__":
    run()
