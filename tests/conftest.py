from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ativos_cli import config
from ativos_cli.models import CatalogEntry, FetchResult, FetchStatus, FundData
from ativos_cli.repositories.asset_repository import AssetRepository
from ativos_cli.repositories.database import connect
from ativos_cli.scraper.parser import parse_catalog
from ativos_cli.services.asset_service import AssetService
from ativos_cli.services.search_service import SearchService
from ativos_cli.utils.dates import now_utc

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def ok_result(ticker: str, data: FundData | None = None, age: timedelta = timedelta(0)):
    return FetchResult(
        ticker=ticker,
        status=FetchStatus.OK,
        source_url=config.fund_url(ticker),
        fetched_at=now_utc() - age,
        data=data or FundData(ticker=ticker, name=f"Fundo {ticker}"),
    )


def failed_result(ticker: str, status=FetchStatus.ERROR, error="Tempo esgotado ao consultar."):
    return FetchResult(
        ticker=ticker,
        status=status,
        source_url=config.fund_url(ticker),
        fetched_at=now_utc(),
        error=error,
    )


class FakeFetcher:
    """Devolve resultados pré-definidos. Ticker desconhecido vira 404."""

    def __init__(self) -> None:
        self.results: dict[str, FetchResult] = {}
        self.catalog: list[CatalogEntry] = []
        self.calls: list[list[str]] = []
        self.catalog_calls = 0
        self.catalog_error: Exception | None = None

    def set_data(self, ticker: str, **fields) -> None:
        self.results[ticker] = ok_result(ticker, FundData(ticker=ticker, **fields))

    def fetch(self, tickers, on_result=None):
        self.calls.append(list(tickers))
        out = []
        for ticker in tickers:
            result = self.results.get(ticker) or failed_result(
                ticker, FetchStatus.NOT_FOUND, f"Ativo {ticker} não encontrado."
            )
            result = result.model_copy(update={"fetched_at": now_utc()})
            out.append(result)
            if on_result:
                on_result(result)
        return out

    def fetch_catalog(self):
        self.catalog_calls += 1
        if self.catalog_error:
            raise self.catalog_error
        return self.catalog


@pytest.fixture
def fetcher() -> FakeFetcher:
    f = FakeFetcher()
    # Valores do aviso de setembro/2026 de cada fundo.
    f.set_data(
        "MXRF11",
        name="Maxi Renda",
        datacom=date(2026, 9, 30),
        rendimento=Decimal("0.1"),
        cotacao_base=Decimal("9.17"),
        rendimento_pct=Decimal("1.0905"),
        data_pagamento=date(2026, 10, 15),
        datacom_anterior=date(2026, 8, 29),
        rendimento_anterior=Decimal("0.09"),
        rendimento_pct_anterior=Decimal("0.9836"),
        cotacao_base_anterior=Decimal("9.15"),
        source_field="aviso 1335757",
    )
    f.set_data(
        "KNCR11",
        name="Kinea Rendimentos Imobiliários",
        datacom=date(2026, 9, 30),
        rendimento=Decimal("1.13"),
        cotacao_base=Decimal("106.4"),
        rendimento_pct=Decimal("1.0620"),
        data_pagamento=date(2026, 10, 14),
        source_field="aviso 1335000",
    )
    f.catalog = parse_catalog(fixture_text("fiis_lista.html"))
    return f


@pytest.fixture
def repo(tmp_path) -> AssetRepository:
    return AssetRepository(connect(tmp_path / "ativos.db"))


@pytest.fixture
def service(repo, fetcher) -> AssetService:
    return AssetService(repo, fetcher)


@pytest.fixture
def search(repo, fetcher) -> SearchService:
    return SearchService(repo, fetcher)
