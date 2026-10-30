"""Spiders testados com respostas simuladas (sem rede)."""

import json

import pytest
from scrapy.http import HtmlResponse, Request

from ativos_cli.models import FetchStatus
from ativos_cli.scraper.pipelines import JsonLinesStdoutPipeline
from ativos_cli.scraper.runner import scrapy_settings
from ativos_cli.scraper.spiders.fiis import CatalogSpider, FundSpider
from tests.conftest import fixture_text


def response(url: str, body: str, status: int = 200) -> HtmlResponse:
    return HtmlResponse(
        url=url, status=status, body=body.encode("utf-8"), encoding="utf-8", request=Request(url)
    )


def test_ok_page():
    result = FundSpider.build_result(
        response("https://fiis.com.br/mxrf11/", fixture_text("fiis_mxrf11.html")), "MXRF11"
    )
    assert result.status == FetchStatus.OK
    assert result.data.ticker == "MXRF11"
    assert result.source_url == "https://fiis.com.br/mxrf11/"


def test_not_found():
    result = FundSpider.build_result(
        response("https://fiis.com.br/zzzz11/", fixture_text("fiis_404.html"), 404), "ZZZZ11"
    )
    assert result.status == FetchStatus.NOT_FOUND
    assert result.data is None


@pytest.mark.parametrize(
    ("status", "message"),
    [(429, "Limite de requisições"), (503, "problemas"), (403, "negado"), (301, "inesperada")],
)
def test_unexpected_http(status, message):
    result = FundSpider.build_result(response("https://fiis.com.br/x/", "", status), "MXRF11")
    assert result.status == FetchStatus.ERROR
    assert message in result.error


def test_changed_structure_is_error_not_fake_data():
    result = FundSpider.build_result(
        response("https://fiis.com.br/mxrf11/", "<html>layout novo</html>"), "MXRF11"
    )
    assert result.status == FetchStatus.ERROR
    assert result.data is None
    assert "Estrutura" in result.error


def test_catalog_spider():
    spider = CatalogSpider()
    items = list(spider.parse(response("https://fiis.com.br/x/", fixture_text("fiis_lista.html"))))
    assert len(items) == 1
    assert any(e["ticker"] == "MXRF11" for e in items[0]["entries"])


def test_items_are_json_serializable(capsys):
    spider = FundSpider(tickers=["MXRF11"])
    resp = response("https://fiis.com.br/mxrf11/", fixture_text("fiis_mxrf11.html"))
    resp.request.cb_kwargs["ticker"] = "MXRF11"
    item = next(iter(spider.parse(resp, ticker="MXRF11")))
    JsonLinesStdoutPipeline().process_item(item)
    line = json.loads(capsys.readouterr().out)
    assert line["kind"] == "fund"
    assert line["data"]["rendimento"] == "0.1"


def test_settings_respect_site_limits():
    settings = scrapy_settings()
    assert settings["ROBOTSTXT_OBEY"] is True
    assert settings["CONCURRENT_REQUESTS_PER_DOMAIN"] == 1
    assert settings["DOWNLOAD_DELAY"] >= 1
    assert 429 in settings["RETRY_HTTP_CODES"]
