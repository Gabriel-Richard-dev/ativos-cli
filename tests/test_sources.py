import json
from datetime import date
from decimal import Decimal

import pytest

from ativos_cli.errors import ParseError
from ativos_cli.models import FetchStatus
from ativos_cli.scraper import b3, cvm, fundosnet
from ativos_cli.scraper.fetcher import OfficialFetcher
from ativos_cli.scraper.http import HttpStatusError
from tests.conftest import FIXTURES, fixture_text

CNPJ = "97521225000125"
NOTICE_ID = 1365016  # aviso de outubro/2026 do MXRF11 (fixture)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeHttp:
    """Responde por URL; conta as requisições. URL desconhecida vira 404."""

    def __init__(self, routes: dict[str, bytes]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def get(self, url, headers=None):
        self.requests.append(url)
        if url not in self.routes:
            raise HttpStatusError(404, url)
        return self.routes[url]


def mxrf_routes(cotahist_day: date | None = date(2026, 10, 30)) -> dict[str, bytes]:
    search = fixture_text("fnet_busca_mxrf11.json")
    routes = {
        "https://fiis.com.br/mxrf11/": fixture_bytes("fiis_mxrf11.html"),
        fundosnet.search_url(CNPJ): search.encode(),
        fundosnet.document_url(NOTICE_ID): fixture_bytes("fnet_aviso_mxrf11.xml"),
    }
    if cotahist_day:
        # Reaproveita o arquivo de 29/10 como se fosse o fechamento da data-com.
        routes[f"{b3.BASE_URL}/{b3.cotahist_name(cotahist_day)}"] = fixture_bytes(
            "COTAHIST_D29102026.ZIP"
        )
    return routes


class TestFundosNet:
    def test_parse_notice(self):
        dividend = fundosnet.parse_notice(
            fixture_bytes("fnet_aviso_mxrf11.xml"), "MXRF11", NOTICE_ID
        )
        assert dividend.datacom == date(2026, 10, 30)
        assert dividend.valor == Decimal("0.095")
        assert dividend.data_pagamento == date(2026, 11, 16)

    def test_notice_for_other_ticker(self):
        xml = fixture_bytes("fnet_aviso_mxrf11.xml")
        assert fundosnet.parse_notice(xml, "KNCR11", NOTICE_ID) is None

    def test_parse_search(self):
        notices = fundosnet.parse_search(fixture_text("fnet_busca_mxrf11.json").encode())
        assert [n.id for n in notices] == [1365016, 1335757, 1305736]

    def test_broken_documents(self):
        with pytest.raises(ParseError):
            fundosnet.parse_notice(b"<quebrado", "MXRF11", 1)
        with pytest.raises(ParseError):
            fundosnet.parse_search(b"<html>")

    def test_dividend_roundtrip(self):
        dividend = fundosnet.Dividend(date(2026, 10, 30), Decimal("0.095"), None, 1)
        assert fundosnet.Dividend.from_dict(dividend.to_dict()) == dividend


class TestCotahist:
    def test_parse_closing_prices(self):
        closes = b3.parse_cotahist(fixture_bytes("COTAHIST_D29102026.ZIP"))
        assert closes["MXRF11"] == Decimal("8.94")
        assert closes["KNCR11"] == Decimal("104.30")

    def test_invalid_file(self):
        with pytest.raises(ParseError):
            b3.parse_cotahist(b"nao e zip")

    def test_parse_quote(self):
        payload = fixture_bytes("b3_cotacao_mxrf11.json")
        assert b3.parse_quote(payload, "MXRF11") == Decimal("8.88")
        assert b3.parse_quote(payload, "KNCR11") is None
        assert b3.parse_quote(b'{"Trad": []}', "MXRF11") is None
        with pytest.raises(ParseError):
            b3.parse_quote(b"<html>", "MXRF11")


class TestOfficialFetcher:
    def test_fetch_combines_sources(self, tmp_path):
        fetcher = OfficialFetcher(tmp_path, http=FakeHttp(mxrf_routes()))
        [result] = fetcher.fetch(["MXRF11"])
        assert result.status == FetchStatus.OK, result.error
        data = result.data
        assert data.name == "Maxi Renda"
        assert data.datacom == date(2026, 10, 30)
        assert data.rendimento == Decimal("0.095")
        assert data.data_pagamento == date(2026, 11, 16)
        assert data.cotacao_base == Decimal("8.94")
        assert str(data.rendimento_pct) == "1.0626"  # 0,095 / 8,94 = 1,06263...
        assert result.source_url == fundosnet.notice_page_url(NOTICE_ID)

    def test_stops_at_newest_notice(self, tmp_path):
        http = FakeHttp(mxrf_routes())
        OfficialFetcher(tmp_path, http=http).fetch(["MXRF11"])
        downloads = [u for u in http.requests if "downloadDocumento" in u]
        assert downloads == [fundosnet.document_url(NOTICE_ID)]

    def test_skips_notice_of_another_class(self, tmp_path):
        routes = mxrf_routes()
        routes[fundosnet.document_url(NOTICE_ID)] = b"<DadosEconomicoFinanceiros/>"
        routes[fundosnet.document_url(1335757)] = fixture_bytes("fnet_aviso_mxrf11.xml")
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["MXRF11"])
        assert result.data.source_field == "aviso 1335757"

    def test_second_fetch_only_searches_notices(self, tmp_path):
        OfficialFetcher(tmp_path, http=FakeHttp(mxrf_routes())).fetch(["MXRF11"])
        http = FakeHttp(mxrf_routes())
        [result] = OfficialFetcher(tmp_path, http=http).fetch(["MXRF11"])
        assert result.status == FetchStatus.OK
        assert http.requests == [fundosnet.search_url(CNPJ)]

    def test_closing_price_not_published_yet(self, tmp_path):
        fetcher = OfficialFetcher(tmp_path, http=FakeHttp(mxrf_routes(cotahist_day=None)))
        [result] = fetcher.fetch(["MXRF11"])
        assert result.status == FetchStatus.OK
        assert result.data.rendimento == Decimal("0.095")
        assert result.data.cotacao_base is None
        assert result.data.rendimento_pct is None

    def test_provisional_price_before_official_close(self, tmp_path):
        routes = mxrf_routes(cotahist_day=None)
        routes[b3.quote_url("MXRF11")] = fixture_bytes("b3_cotacao_mxrf11.json")
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["MXRF11"])
        assert result.data.cotacao_base == Decimal("8.88")
        assert result.data.cotacao_provisoria is True
        assert str(result.data.rendimento_pct) == "1.0698"  # 0,095 / 8,88 = 1,06981...

    def test_official_close_skips_quote(self, tmp_path):
        http = FakeHttp(mxrf_routes())
        [result] = OfficialFetcher(tmp_path, http=http).fetch(["MXRF11"])
        assert result.data.cotacao_provisoria is False
        assert b3.quote_url("MXRF11") not in http.requests

    def test_unknown_ticker(self, tmp_path):
        [result] = OfficialFetcher(tmp_path, http=FakeHttp({})).fetch(["ZZZZ11"])
        assert result.status == FetchStatus.NOT_FOUND

    def test_one_failure_does_not_stop_others(self, tmp_path):
        routes = mxrf_routes()
        routes["https://fiis.com.br/kncr11/"] = fixture_bytes("fiis_kncr11.html")
        results = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["KNCR11", "MXRF11"])
        assert [r.ticker for r in results] == ["KNCR11", "MXRF11"]
        assert results[0].status == FetchStatus.ERROR  # busca do FundosNet do KNCR11 falhou
        assert results[1].status == FetchStatus.OK


PMLL_CNPJ = "26499833000132"


class TestRegistry:
    def registry(self, tmp_path, routes=None):
        routes = routes or {
            f"{cvm.BASE_URL}/{cvm.file_name(date.today().year)}": fixture_bytes(
                "inf_mensal_fii_2026.zip"
            )
        }
        return cvm.Registry(FakeHttp(routes), tmp_path)

    def test_by_ticker_uses_isin(self, tmp_path):
        fund = self.registry(tmp_path).by_ticker("MXRF11")
        assert fund.cnpj == "97521225000125"

    def test_renamed_fund_keeps_old_isin(self, tmp_path):
        registry = self.registry(tmp_path)
        assert registry.by_ticker("PMLL11") is None
        assert registry.by_ticker("MALL11").cnpj == PMLL_CNPJ

    def test_by_name_ignores_accents_and_suffixes(self, tmp_path):
        fund = self.registry(tmp_path).by_name(
            "PATRIA MALLS FUNDO DE INVESTIMENTO IMOBILIÁRIO - RESPONSABILIDADE LIMITADA"
        )
        assert fund.cnpj == PMLL_CNPJ

    def test_falls_back_to_previous_year(self, tmp_path):
        year = date.today().year
        routes = {
            f"{cvm.BASE_URL}/{cvm.file_name(year - 1)}": fixture_bytes("inf_mensal_fii_2026.zip")
        }
        assert self.registry(tmp_path, routes).by_ticker("KNCR11") is not None

    def test_b3_fund_name(self):
        payload = fixture_bytes("b3_fundos_pmll.json")
        assert b3.parse_fund_name(payload, "PMLL11").startswith("PATRIA MALLS")
        assert b3.parse_fund_name(payload, "MXRF11") is None


class TestFundWithoutFiisPage:
    def routes(self):
        notice = 1365847
        search = json.dumps({"data": [{"id": notice, "dataEntrega": "30/10/2026 17:00"}]}).encode()
        xml = fixture_bytes("fnet_aviso_mxrf11.xml").replace(b"MXRF11", b"PMLL11")
        return {
            f"{cvm.BASE_URL}/{cvm.file_name(date.today().year)}": fixture_bytes(
                "inf_mensal_fii_2026.zip"
            ),
            b3.funds_search_url("PMLL11"): fixture_bytes("b3_fundos_pmll.json"),
            fundosnet.search_url(PMLL_CNPJ): search,
            fundosnet.document_url(notice): xml,
        }

    def test_renamed_fund_found_by_name(self, tmp_path):
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(self.routes())).fetch(["PMLL11"])
        assert result.status == FetchStatus.OK, result.error
        assert result.data.name.startswith("PATRIA MALLS")
        assert result.data.datacom == date(2026, 10, 30)

    def test_identity_is_cached(self, tmp_path):
        OfficialFetcher(tmp_path, http=FakeHttp(self.routes())).fetch(["PMLL11"])
        http = FakeHttp(self.routes())
        OfficialFetcher(tmp_path, http=http).fetch(["PMLL11"])
        assert not any("fiis.com.br" in u or "cvm.gov.br" in u for u in http.requests)

    def test_unknown_everywhere_is_not_found(self, tmp_path):
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(self.routes())).fetch(["ZZZZ11"])
        assert result.status == FetchStatus.NOT_FOUND
