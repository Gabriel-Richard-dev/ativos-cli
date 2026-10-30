from collections.abc import Callable
from typing import Protocol

from ativos_cli.models import CatalogEntry, FetchResult

ResultCallback = Callable[[FetchResult], None]


class Fetcher(Protocol):
    """Fonte de dados. Implementada por OfficialFetcher; substituível nos testes."""

    def fetch(
        self, tickers: list[str], on_result: ResultCallback | None = None
    ) -> list[FetchResult]: ...

    def fetch_catalog(self) -> list[CatalogEntry]: ...
