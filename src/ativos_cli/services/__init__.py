from typing import Protocol

from ativos_cli.models import CatalogEntry, FetchResult
from ativos_cli.scraper.runner import ResultCallback


class Fetcher(Protocol):
    """Fonte de dados. Implementada por ScrapyFetcher; substituível nos testes."""

    def fetch(
        self, tickers: list[str], on_result: ResultCallback | None = None
    ) -> list[FetchResult]: ...

    def fetch_catalog(self) -> list[CatalogEntry]: ...
