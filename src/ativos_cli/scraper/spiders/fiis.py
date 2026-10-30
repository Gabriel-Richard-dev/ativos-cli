"""Spiders do fiis.com.br. Cada resposta vira um item JSON (ver pipelines.py)."""

from typing import Any

import scrapy
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Response
from twisted.internet.error import (
    ConnectionRefusedError,
    DNSLookupError,
    TCPTimedOutError,
    TimeoutError,
)
from twisted.python.failure import Failure

from ativos_cli import config
from ativos_cli.errors import ParseError
from ativos_cli.models import FetchResult, FetchStatus
from ativos_cli.scraper.parser import parse_catalog, parse_fund_page
from ativos_cli.utils.dates import now_utc


def describe_http_status(status: int) -> str:
    if status == 429:
        return "Limite de requisições atingido (HTTP 429). Tente novamente mais tarde."
    if status == 403:
        return "Acesso negado pelo site (HTTP 403)."
    if status >= 500:
        return f"O site está com problemas (HTTP {status})."
    return f"Resposta inesperada do site (HTTP {status})."


def describe_failure(failure: Failure) -> str:
    if failure.check(TimeoutError, TCPTimedOutError):
        return "Tempo esgotado ao consultar o site."
    if failure.check(DNSLookupError, ConnectionRefusedError):
        return "Falha de conexão. Verifique sua internet."
    if failure.check(IgnoreRequest):
        return "Consulta bloqueada pelas regras de acesso do site (robots.txt)."
    return f"Falha de conexão: {failure.getErrorMessage() or failure.type.__name__}"


class FundSpider(scrapy.Spider):
    name = "fiis_fund"
    allowed_domains = ["fiis.com.br"]

    def __init__(self, tickers: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tickers = tickers

    async def start(self):
        for ticker in self.tickers:
            yield scrapy.Request(
                config.fund_url(ticker),
                callback=self.parse,
                errback=self.on_error,
                cb_kwargs={"ticker": ticker},
                dont_filter=True,
            )

    def parse(self, response: Response, ticker: str):
        yield {"kind": "fund", **self.build_result(response, ticker).model_dump(mode="json")}

    def on_error(self, failure: Failure):
        ticker = failure.request.cb_kwargs["ticker"]
        response = getattr(failure.value, "response", None)
        if response is not None:
            result = self.build_result(response, ticker)
        else:
            result = FetchResult(
                ticker=ticker,
                status=FetchStatus.ERROR,
                source_url=failure.request.url,
                fetched_at=now_utc(),
                error=describe_failure(failure),
            )
        yield {"kind": "fund", **result.model_dump(mode="json")}

    @staticmethod
    def build_result(response: Response, ticker: str) -> FetchResult:
        result = FetchResult(
            ticker=ticker,
            status=FetchStatus.ERROR,
            source_url=config.fund_url(ticker),
            fetched_at=now_utc(),
        )
        if response.status == 404:
            result.status = FetchStatus.NOT_FOUND
            result.error = f"Ativo {ticker} não encontrado no {config.SOURCE_NAME}."
            return result
        if response.status != 200:
            result.error = describe_http_status(response.status)
            return result
        try:
            result.data = parse_fund_page(response.text, expected_ticker=ticker)
        except ParseError as exc:
            result.error = str(exc)
            return result
        result.status = FetchStatus.OK
        return result


class CatalogSpider(scrapy.Spider):
    name = "fiis_catalog"
    allowed_domains = ["fiis.com.br"]

    async def start(self):
        yield scrapy.Request(config.CATALOG_URL, callback=self.parse, errback=self.on_error)

    def parse(self, response: Response):
        if response.status != 200:
            yield {"kind": "catalog", "error": describe_http_status(response.status)}
            return
        try:
            entries = parse_catalog(response.text)
        except ParseError as exc:
            yield {"kind": "catalog", "error": str(exc)}
            return
        yield {"kind": "catalog", "entries": [e.model_dump(mode="json") for e in entries]}

    def on_error(self, failure: Failure):
        yield {"kind": "catalog", "error": describe_failure(failure)}
