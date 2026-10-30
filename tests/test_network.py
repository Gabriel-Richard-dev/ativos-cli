"""Integração com as fontes reais. Fora da execução padrão: rode com `pytest -m network`."""

import pytest

from ativos_cli.models import FetchStatus
from ativos_cli.scraper.fetcher import OfficialFetcher

pytestmark = pytest.mark.network


def test_fetch_real_fund(tmp_path):
    result, missing = OfficialFetcher(tmp_path).fetch(["MXRF11", "ZZZZ11"])
    assert result.status == FetchStatus.OK, result.error
    assert result.data.datacom is not None
    assert result.data.rendimento is not None
    assert "fnet.bmfbovespa.com.br" in result.source_url
    assert missing.status == FetchStatus.NOT_FOUND


def test_fetch_real_catalog(tmp_path):
    entries = OfficialFetcher(tmp_path).fetch_catalog()
    assert any(e.ticker == "MXRF11" for e in entries)
