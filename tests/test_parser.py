import json
from datetime import date
from decimal import Decimal

import pytest

from ativos_cli.errors import ParseError
from ativos_cli.scraper.parser import (
    is_valid_ticker,
    normalize_ticker,
    parse_catalog,
    parse_fund_page,
)
from ativos_cli.utils.dates import format_date, parse_date
from ativos_cli.utils.money import format_brl, to_decimal
from tests.conftest import fixture_text


def page_with(meta: dict) -> str:
    """Página mínima com a mesma estrutura do fiis.com.br."""
    layer = {"pageTitle": "x", "pagePostTerms": {"meta": {"ticker": "TEST11", **meta}}}
    return f"<html><script>var dataLayer_content = {json.dumps(layer)};</script></html>"


class TestFundPage:
    def test_mxrf11_priority_fields(self):
        data = parse_fund_page(fixture_text("fiis_mxrf11.html"), expected_ticker="MXRF11")
        assert data.ticker == "MXRF11"
        assert data.name == "Maxi Renda"
        assert data.datacom == date(2026, 9, 30)
        assert data.rendimento == Decimal("0.1")
        assert data.cotacao_base == Decimal("9.17")

    def test_datacom_is_not_payment_date(self):
        data = parse_fund_page(fixture_text("fiis_mxrf11.html"))
        assert data.data_pagamento == date(2026, 10, 15)
        assert data.datacom != data.data_pagamento

    def test_cotacao_base_is_not_current_price(self):
        data = parse_fund_page(fixture_text("fiis_mxrf11.html"))
        assert data.cotacao_atual == Decimal("8.98")
        assert data.cotacao_base != data.cotacao_atual

    def test_kncr11(self):
        data = parse_fund_page(fixture_text("fiis_kncr11.html"), expected_ticker="kncr11")
        assert data.name == "Kinea Rendimentos Imobiliários"
        assert (data.datacom, data.rendimento, data.cotacao_base) == (
            date(2026, 9, 30),
            Decimal("1.13"),
            Decimal("106.4"),
        )

    def test_values_keep_decimal_precision(self):
        data = parse_fund_page(page_with({"ur_data_base": "2026-01-30", "ur_valor": 0.0825}))
        assert data.rendimento == Decimal("0.0825")
        assert isinstance(data.rendimento, Decimal)

    def test_next_dividend_wins_when_more_recent(self):
        data = parse_fund_page(
            page_with(
                {
                    "ur_data_base": "2026-09-30T00:00:00",
                    "ur_valor": 0.1,
                    "ur_cotacao_base": 9.17,
                    "pr_database": "2026-10-30T00:00:00",
                    "pr_valor": 0.11,
                    "pr_cotacaobase": 9.01,
                }
            )
        )
        assert data.datacom == date(2026, 10, 30)
        assert data.rendimento == Decimal("0.11")
        assert data.cotacao_base == Decimal("9.01")
        assert data.source_field == "pr_*"

    def test_last_dividend_used_when_next_is_older(self):
        data = parse_fund_page(
            page_with(
                {
                    "ur_data_base": "2026-09-30",
                    "ur_valor": 0.1,
                    "pr_database": "2026-08-29",
                    "pr_valor": 0.12,
                }
            )
        )
        assert data.datacom == date(2026, 9, 30)
        assert data.source_field == "ur_*"

    def test_value_without_date_is_ambiguous(self):
        data = parse_fund_page(page_with({"ur_valor": 0.1, "ur_cotacao_base": 9.0}))
        assert data.datacom is None
        assert data.rendimento is None
        assert data.notes

    def test_missing_dividend_fields(self):
        data = parse_fund_page(page_with({"nome_pregao": "Teste"}))
        assert data.name == "Teste"
        assert (data.datacom, data.rendimento, data.cotacao_base) == (None, None, None)

    def test_zeroed_date_is_missing(self):
        data = parse_fund_page(page_with({"ur_data_base": "0001-01-01T00:00:00", "ur_valor": 0}))
        assert data.datacom is None

    def test_other_ticker_is_error(self):
        with pytest.raises(ParseError, match="outro ativo"):
            parse_fund_page(fixture_text("fiis_mxrf11.html"), expected_ticker="KNCR11")

    def test_not_found_page_has_no_fund_data(self):
        with pytest.raises(ParseError):
            parse_fund_page(fixture_text("fiis_404.html"))

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
            parse_fund_page(html)


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
