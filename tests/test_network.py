"""Integração com o site real. Fora da execução padrão: rode com `pytest -m network`."""

import pytest

from ativos_cli.models import FetchStatus
from ativos_cli.scraper.runner import ScrapyFetcher

pytestmark = pytest.mark.network


def test_fetch_real_fund():
    result, missing = ScrapyFetcher().fetch(["MXRF11", "ZZZZ11"])
    assert result.status == FetchStatus.OK
    assert result.data.datacom is not None
    assert result.data.rendimento is not None
    assert result.data.cotacao_base is not None
    assert missing.status == FetchStatus.NOT_FOUND


def test_fetch_real_catalog():
    entries = ScrapyFetcher().fetch_catalog()
    assert any(e.ticker == "MXRF11" for e in entries)
