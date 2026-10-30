import json
from datetime import date
from decimal import Decimal

import pytest

from ativos_cli.errors import ParseError
from ativos_cli.scraper.parser import (
    is_valid_ticker,
    normalize_ticker,
    parse_catalog,
    parse_fund_identity,
)
from ativos_cli.utils.dates import format_date, parse_date
from ativos_cli.utils.money import format_brl, format_percent, to_decimal, truncate
from tests.conftest import fixture_text


def page_with(meta: dict) -> str:
    """Página mínima com a mesma estrutura do fiis.com.br."""
    layer = {"pageTitle": "x", "pagePostTerms": {"meta": {"ticker": "TEST11", **meta}}}
    return f"<html><script>var dataLayer_content = {json.dumps(layer)};</script></html>"


class TestFundIdentity:
    def test_mxrf11(self):
        identity = parse_fund_identity(fixture_text("fiis_mxrf11.html"), expected_ticker="MXRF11")
        assert identity.ticker == "MXRF11"
        assert identity.name == "Maxi Renda"
        assert identity.cnpj == "97521225000125"

    def test_ticker_is_normalized(self):
        identity = parse_fund_identity(fixture_text("fiis_kncr11.html"), expected_ticker="kncr11")
        assert identity.cnpj == "16706958000132"

    def test_missing_cnpj_is_error(self):
        with pytest.raises(ParseError, match="CNPJ"):
            parse_fund_identity(page_with({"nome_pregao": "Teste"}))

    def test_other_ticker_is_error(self):
        with pytest.raises(ParseError, match="outro ativo"):
            parse_fund_identity(fixture_text("fiis_mxrf11.html"), expected_ticker="KNCR11")

    def test_not_found_page_has_no_fund_data(self):
        with pytest.raises(ParseError):
            parse_fund_identity(fixture_text("fiis_404.html"))

    @pytest.mark.parametrize(
        "html",
        [
            "<html><body>sem dados</body></html>",
            "<script>var dataLayer_content = {quebrado</script>",
            '<script>var dataLayer_content = {"pageTitle": "x"};</script>',
        ],
    )
    def test_structure_change(self, html):
        with pytest.raises(ParseError, match="Estrutura"):
            parse_fund_identity(html)


class TestCatalog:
    def test_parse_catalog(self):
        entries = parse_catalog(fixture_text("fiis_lista.html"))
        by_ticker = {e.ticker: e.name for e in entries}
        assert len(entries) > 500
        assert by_ticker["MXRF11"] == "Maxi Renda"
        assert by_ticker["KNCR11"]

    def test_catalog_structure_change(self):
        with pytest.raises(ParseError):
            parse_catalog("<html></html>")


class TestTicker:
    @pytest.mark.parametrize("raw", ["MXRF11", " mxrf11 ", "ARFI11B"])
    def test_valid(self, raw):
        assert is_valid_ticker(normalize_ticker(raw))

    @pytest.mark.parametrize("raw", ["", "MXRF", "MX11", "MXRF111", "MXRF-11", "12345"])
    def test_invalid(self, raw):
        assert not is_valid_ticker(normalize_ticker(raw))


class TestNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (Decimal("9.17"), Decimal("9.17")),
            ("9.17", Decimal("9.17")),
            ("1.234,56", Decimal("1234.56")),
            ("R$ 0,10", Decimal("0.10")),
            (10, Decimal(10)),
            ("", None),
            ("N/D", None),
            ("abc", None),
            (None, None),
            (True, None),
            (9.17, None),  # float binário é rejeitado
        ],
    )
    def test_to_decimal(self, raw, expected):
        assert to_decimal(raw) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("0.1"), "R$ 0,10"),
            (Decimal("9.17"), "R$ 9,17"),
            (Decimal("1234.5"), "R$ 1.234,50"),
            (Decimal("0.0825"), "R$ 0,0825"),
            (Decimal("100"), "R$ 100,00"),
            (None, "N/D"),
        ],
    )
    def test_format_brl(self, value, expected):
        assert format_brl(value) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-09-30T00:00:00", date(2026, 9, 30)),
            ("2026-09-30", date(2026, 9, 30)),
            ("30/09/2026", date(2026, 9, 30)),
            ("2026-02-30", None),
            ("0001-01-01T00:00:00", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse_date(self, raw, expected):
        assert parse_date(raw) == expected

    def test_format_date(self):
        assert format_date(date(2026, 10, 30)) == "30/10/2026"
        assert format_date(None) == "N/D"


def test_truncate_cuts_without_rounding():
    assert truncate(Decimal("1.0909"), 3) == Decimal("1.090")
    assert format_percent(truncate(Decimal("0.5"), 3)) == "0,500%"
    assert truncate(None, 3) is None
    assert format_percent(None) == "N/D"
