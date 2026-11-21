import json
from datetime import date
from decimal import Decimal

import pytest

from ativos_cli.errors import FetchError, ParseError
from ativos_cli.models import AssetType, FetchStatus
from ativos_cli.scraper import b3, buenavista, cvm, fundosnet, statusinvest
from ativos_cli.scraper import fetcher as fetcher_module
from ativos_cli.scraper.fetcher import OfficialFetcher
from ativos_cli.scraper.http import HttpStatusError
from tests.conftest import FIXTURES, fixture_text

CNPJ = "97521225000125"
NOTICE_ID = 1365016  # aviso de outubro/2026 do MXRF11 (fixture)
PREVIOUS_NOTICE_ID = 1335757  # aviso de setembro/2026


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
        fundosnet.document_url(PREVIOUS_NOTICE_ID): fixture_bytes("fnet_aviso_mxrf11_set.xml"),
        # Fechamento da data-com anterior (30/09); o arquivo de 29/10 faz as vezes dele.
        f"{b3.BASE_URL}/{b3.cotahist_name(date(2026, 9, 30))}": fixture_bytes(
            "COTAHIST_D29102026.ZIP"
        ),
        # Lista de ETFs: com ela em cache, consultar um FII não a baixa de novo.
        b3.etf_list_url("ETF", 1): fixture_bytes("b3_etfs.json"),
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

    def test_previous_dividend(self, tmp_path):
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(mxrf_routes())).fetch(["MXRF11"])
        data = result.data
        assert data.datacom_anterior == date(2026, 9, 30)
        assert data.rendimento_anterior == Decimal("0.10")
        assert data.cotacao_base_anterior == Decimal("8.94")
        assert str(data.rendimento_pct_anterior) == "1.1185"  # 0,10 / 8,94 = 1,11856...
        assert data.source_field == f"aviso {NOTICE_ID}"

    def test_stops_at_previous_notice(self, tmp_path):
        http = FakeHttp(mxrf_routes())
        OfficialFetcher(tmp_path, http=http).fetch(["MXRF11"])
        downloads = [u for u in http.requests if "downloadDocumento" in u]
        assert downloads == [
            fundosnet.document_url(NOTICE_ID),
            fundosnet.document_url(PREVIOUS_NOTICE_ID),
        ]

    def test_rectified_notice_is_not_previous(self, tmp_path):
        routes = mxrf_routes()
        # Retificação: o segundo aviso repete a data-com do atual.
        routes[fundosnet.document_url(PREVIOUS_NOTICE_ID)] = fixture_bytes("fnet_aviso_mxrf11.xml")
        routes[fundosnet.document_url(1305736)] = fixture_bytes("fnet_aviso_mxrf11_set.xml")
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["MXRF11"])
        assert result.data.datacom == date(2026, 10, 30)
        assert result.data.datacom_anterior == date(2026, 9, 30)

    def test_previous_notice_failure_keeps_current(self, tmp_path):
        routes = mxrf_routes()
        del routes[fundosnet.document_url(PREVIOUS_NOTICE_ID)]
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["MXRF11"])
        assert result.status == FetchStatus.OK
        assert result.data.rendimento == Decimal("0.095")
        assert result.data.datacom_anterior is None

    def test_previous_without_closing_price(self, tmp_path):
        routes = mxrf_routes()
        del routes[f"{b3.BASE_URL}/{b3.cotahist_name(date(2026, 9, 30))}"]
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["MXRF11"])
        assert result.data.rendimento_anterior == Decimal("0.10")
        assert result.data.cotacao_base_anterior is None
        assert result.data.rendimento_pct_anterior is None

    def test_skips_notice_of_another_class(self, tmp_path):
        routes = mxrf_routes()
        routes[fundosnet.document_url(NOTICE_ID)] = b"<DadosEconomicoFinanceiros/>"
        routes[fundosnet.document_url(1335757)] = fixture_bytes("fnet_aviso_mxrf11.xml")
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["MXRF11"])
        assert result.data.source_field == "aviso 1335757"
        assert result.data.datacom_anterior is None  # o aviso seguinte não está disponível

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


class FakeBrowser:
    """Devolve páginas do Status Invest por URL; sem a URL, falha como o Chrome."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requests: list[str] = []
        self.closed = False

    def get(self, url):
        self.requests.append(url)
        if url not in self.pages:
            raise FetchError("Chrome indisponível para abrir o Status Invest.")
        return self.pages[url]

    def close(self):
        self.closed = True


class TestStatusInvest:
    def test_parse_cards(self):
        last, upcoming = statusinvest.parse_cards(fixture_text("statusinvest_mxrf11.html"))
        assert last.datacom == date(2026, 9, 30)
        assert last.cotacao_base == Decimal("9.17")
        assert last.rendimento_pct == Decimal("1.0905")
        assert upcoming.rendimento == Decimal("0.0950")
        assert upcoming.cotacao_base == Decimal("8.87")
        assert upcoming.rendimento_pct == Decimal("1.0710")
        assert upcoming.datacom == date(2026, 10, 30)
        assert upcoming.data_pagamento == date(2026, 11, 16)

    def test_page_without_cards(self):
        assert statusinvest.parse_cards("<html></html>") == []

    def test_card_overrides_b3_price(self, tmp_path):
        routes = mxrf_routes(cotahist_day=None)
        routes[b3.quote_url("MXRF11")] = fixture_bytes("b3_cotacao_mxrf11.json")
        http = FakeHttp(routes)
        browser = FakeBrowser(
            {statusinvest.page_url("MXRF11"): fixture_text("statusinvest_mxrf11.html")}
        )
        [result] = OfficialFetcher(tmp_path, http=http, browser=browser).fetch(["MXRF11"])
        assert result.data.cotacao_base == Decimal("8.87")
        assert str(result.data.rendimento_pct) == "1.0710"
        assert result.data.cotacao_provisoria is False
        assert b3.quote_url("MXRF11") not in http.requests
        assert browser.closed

    def test_falls_back_to_b3_without_browser(self, tmp_path):
        routes = mxrf_routes(cotahist_day=None)
        routes[b3.quote_url("MXRF11")] = fixture_bytes("b3_cotacao_mxrf11.json")
        fetcher = OfficialFetcher(tmp_path, http=FakeHttp(routes), browser=FakeBrowser({}))
        [result] = fetcher.fetch(["MXRF11"])
        assert result.data.cotacao_base == Decimal("8.88")
        assert result.data.cotacao_provisoria is True

    def test_card_cached_after_datacom(self, tmp_path, monkeypatch):
        class AfterDatacom(date):
            @classmethod
            def today(cls):
                return date(2026, 10, 31)

        monkeypatch.setattr("ativos_cli.scraper.fetcher.date", AfterDatacom)
        page = {statusinvest.page_url("MXRF11"): fixture_text("statusinvest_mxrf11.html")}
        routes = mxrf_routes(cotahist_day=None)
        OfficialFetcher(tmp_path, http=FakeHttp(routes), browser=FakeBrowser(page)).fetch(
            ["MXRF11"]
        )
        browser = FakeBrowser({})
        fetcher = OfficialFetcher(tmp_path, http=FakeHttp(routes), browser=browser)
        [result] = fetcher.fetch(["MXRF11"])
        assert result.data.cotacao_base == Decimal("8.87")
        assert str(result.data.rendimento_pct) == "1.0710"
        assert browser.requests == []

    def test_ignores_card_of_other_datacom(self, tmp_path):
        page = fixture_text("statusinvest_mxrf11.html").replace("30/10/2026", "28/11/2026")
        browser = FakeBrowser({statusinvest.page_url("MXRF11"): page})
        routes = mxrf_routes(cotahist_day=None)
        routes[b3.quote_url("MXRF11")] = fixture_bytes("b3_cotacao_mxrf11.json")
        fetcher = OfficialFetcher(tmp_path, http=FakeHttp(routes), browser=browser)
        [result] = fetcher.fetch(["MXRF11"])
        assert result.data.cotacao_base == Decimal("8.88")
        assert result.data.cotacao_provisoria is True

    def test_official_close_skips_status_invest(self, tmp_path):
        browser = FakeBrowser({})
        fetcher = OfficialFetcher(tmp_path, http=FakeHttp(mxrf_routes()), browser=browser)
        [result] = fetcher.fetch(["MXRF11"])
        assert result.data.cotacao_base == Decimal("8.94")  # COTAHIST
        assert browser.requests == []


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


def cotahist(day: date, closes: dict[str, str]) -> bytes:
    """Arquivo COTAHIST mínimo com o fechamento (PREULT) de cada ticker."""
    import io
    import zipfile

    lines = []
    for ticker, price in closes.items():
        cents = int(Decimal(price) * 100)
        line = f"01{day:%Y%m%d}14{ticker:<12}010".ljust(108) + f"{cents:013d}"
        lines.append(line.ljust(245))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"COTAHIST_D{day:%d%m%Y}.TXT", "\n".join(lines))
    return buffer.getvalue()


def etf_routes(cotahist_day: date | None = date(2026, 11, 9)) -> dict[str, bytes]:
    routes = {
        b3.etf_list_url("ETF", 1): fixture_bytes("b3_etfs.json"),
        b3.supplement_url("NDIV11"): fixture_bytes("b3_proventos_ndiv11.json"),
        f"{b3.BASE_URL}/{b3.cotahist_name(date(2026, 10, 7))}": cotahist(
            date(2026, 10, 7), {"NDIV11": "11.20"}
        ),
    }
    if cotahist_day:
        routes[f"{b3.BASE_URL}/{b3.cotahist_name(cotahist_day)}"] = cotahist(
            cotahist_day, {"NDIV11": "11.50"}
        )
    return routes


class TestEtfs:
    def test_parse_etf_list(self):
        etfs, pages = b3.parse_etf_list(fixture_bytes("b3_etfs.json"))
        assert pages == 1
        assert set(etfs) == {"NDIV11", "BOVA11"}  # código com outro tamanho fica de fora
        assert etfs["NDIV11"].startswith("NU RENDA IBOV SMART DIVIDENDOS (NDIV) FUNDO DE ÍNDICE ")

    def test_parse_distributions(self):
        [current, previous, older] = b3.parse_distributions(
            fixture_bytes("b3_proventos_ndiv11.json"), "NDIV11"
        )
        assert current.datacom == date(2026, 11, 9)
        assert current.valor == Decimal("0.19162490000")
        assert current.data_pagamento == date(2026, 11, 16)
        assert previous.datacom == date(2026, 10, 7)
        assert older.datacom < previous.datacom

    def test_distributions_skip_amortization_and_sum_same_date(self):
        rows = [
            {"isinCode": "BRNDIVCTF004", "label": "RENDIMENTO", "rate": "0,10",
             "lastDatePrior": "09/11/2026", "paymentDate": "16/11/2026"},
            {"isinCode": "BRNDIVCTF004", "label": "DIVIDENDO", "rate": "0,05",
             "lastDatePrior": "09/11/2026", "paymentDate": "16/11/2026"},
            {"isinCode": "BRNDIVCTF004", "label": "AMORTIZAÇÃO", "rate": "5,00",
             "lastDatePrior": "01/12/2026", "paymentDate": "05/12/2026"},
            {"isinCode": "BROUTRCTF000", "label": "RENDIMENTO", "rate": "9,00",
             "lastDatePrior": "02/12/2026", "paymentDate": "05/12/2026"},
        ]  # fmt: skip
        payload = json.dumps({"cashDividends": rows}).encode()
        [only] = b3.parse_distributions(payload, "NDIV11")
        assert only.valor == Decimal("0.15")
        assert b3.parse_distributions(b"", "IMAB11") == []  # renda fixa: resposta vazia
        with pytest.raises(ParseError):
            b3.parse_distributions(b"<html>", "NDIV11")

    def test_fetch_etf(self, tmp_path):
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(etf_routes())).fetch(["NDIV11"])
        assert result.status == FetchStatus.OK, result.error
        data = result.data
        assert data.asset_type == AssetType.ETF
        assert data.name.startswith("NU RENDA IBOV")
        assert data.datacom == date(2026, 11, 9)
        assert data.rendimento == Decimal("0.19162490000")
        assert data.data_pagamento == date(2026, 11, 16)
        assert data.cotacao_base == Decimal("11.5")
        assert str(data.rendimento_pct) == "1.6663"  # 0,1916249 / 11,50 = 1,66630...
        assert data.datacom_anterior == date(2026, 10, 7)
        assert data.cotacao_base_anterior == Decimal("11.2")
        assert result.source_url == b3.supplement_url("NDIV11")

    def test_etf_provisional_price(self, tmp_path):
        routes = etf_routes(cotahist_day=None)
        routes[b3.quote_url("NDIV11")] = json.dumps(
            {"Trad": [{"scty": {"symb": "NDIV11", "mkt": {"nm": "ETF"},
                                "SctyQtn": {"curPrc": 11.4}}}]}
        ).encode()  # fmt: skip
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["NDIV11"])
        assert result.data.cotacao_base == Decimal("11.4")
        assert result.data.cotacao_provisoria is True

    def test_parse_quote_detail(self):
        payload = json.dumps(
            {"Trad": [{"scty": {"symb": "BOVA11", "mkt": {"nm": "ETF"},
                                "SctyQtn": {"curPrc": 169.99, "prcFlcn": -0.8543459}}}]}
        ).encode()  # fmt: skip
        quote = b3.parse_quote_detail(payload, "BOVA11")
        assert quote.price == Decimal("169.99")
        assert quote.change_pct == Decimal("-0.8543459")
        fixed_income = json.dumps(
            {"Trad": [{"scty": {"symb": "IMAB11", "mkt": {"nm": "RendaFixaPrivada"},
                                "SctyQtn": {"curPrc": 118.94, "prcFlcn": 0.2359683}}}]}
        ).encode()  # fmt: skip
        assert b3.parse_quote_detail(fixed_income, "IMAB11").price == Decimal("118.94")

    def test_etf_without_dividends_gets_day_change(self, tmp_path):
        routes = etf_routes()
        routes[b3.supplement_url("BOVA11")] = b'{"cashDividends": []}'
        routes[b3.quote_url("BOVA11")] = json.dumps(
            {"Trad": [{"scty": {"symb": "BOVA11", "mkt": {"nm": "ETF"},
                                "SctyQtn": {"curPrc": 169.99, "prcFlcn": 0.85}}}]}
        ).encode()  # fmt: skip
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["BOVA11"])
        assert result.status == FetchStatus.OK, result.error
        assert result.data.datacom is None
        assert result.data.cotacao_atual == Decimal("169.99")
        assert result.data.variacao_dia == Decimal("0.85")

    def test_etf_list_is_cached(self, tmp_path):
        OfficialFetcher(tmp_path, http=FakeHttp(etf_routes())).fetch(["NDIV11"])
        http = FakeHttp(etf_routes())
        [result] = OfficialFetcher(tmp_path, http=http).fetch(["NDIV11"])
        assert result.status == FetchStatus.OK
        assert http.requests == [b3.supplement_url("NDIV11")]

    def test_crypto_etfs_are_listed(self, tmp_path):
        crypto = {
            "page": {"totalRecords": 1, "totalPages": 1},
            "results": [{"acronym": "ETHY", "fundName": "BUENA VISTA DEX ETHEREUM HIGH INCOME"}],
        }
        routes = etf_routes() | {b3.etf_list_url("ETF-CRIPTO", 1): json.dumps(crypto).encode()}
        etfs = OfficialFetcher(tmp_path, http=FakeHttp(routes)).etfs()
        assert "ETHY11" in etfs
        assert "NDIV11" in etfs

    def test_cached_list_without_new_category_is_refreshed(self, tmp_path):
        OfficialFetcher(tmp_path, http=FakeHttp(etf_routes())).fetch(["NDIV11"])
        # Lista salva por uma versão que ainda não baixava todas as categorias.
        cache = tmp_path / "etfs.json"
        data = json.loads(cache.read_text())
        data["types"] = ["ETF", "ETF-RF", "ETF-FII"]
        cache.write_text(json.dumps(data))
        http = FakeHttp(etf_routes())
        OfficialFetcher(tmp_path, http=http).fetch(["NDIV11"])
        assert b3.etf_list_url("ETF", 1) in http.requests

    def test_empty_list_answer_is_retried(self, tmp_path):
        empty = b'{"page": {"totalRecords": 0, "totalPages": 0}, "results": []}'
        answers = iter([empty, fixture_bytes("b3_etfs.json")])

        class Flaky(FakeHttp):
            def get(self, url, headers=None):
                if url == b3.etf_list_url("ETF", 1):
                    self.requests.append(url)
                    return next(answers)
                return super().get(url, headers)

        fetcher = OfficialFetcher(tmp_path, http=Flaky({}))
        assert "NDIV11" in fetcher.etfs()

    def test_without_etf_list_fiis_still_work(self, tmp_path):
        routes = mxrf_routes()
        del routes[b3.etf_list_url("ETF", 1)]
        routes["https://fiis.com.br/kncr11/"] = fixture_bytes("fiis_kncr11.html")
        http = FakeHttp(routes)
        results = OfficialFetcher(tmp_path, http=http).fetch(["MXRF11", "KNCR11"])
        assert results[0].status == FetchStatus.OK
        # A lista é tentada uma vez por execução, não a cada ticker.
        assert http.requests.count(b3.etf_list_url("ETF", 1)) == 1

    def test_catalog_includes_etfs(self, tmp_path):
        routes = {
            "https://fiis.com.br/lista-de-fundos-imobiliarios/": fixture_bytes("fiis_lista.html"),
            b3.etf_list_url("ETF", 1): fixture_bytes("b3_etfs.json"),
        }
        entries = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch_catalog()
        by_ticker = {e.ticker: e for e in entries}
        assert by_ticker["NDIV11"].asset_type == AssetType.ETF
        assert by_ticker["MXRF11"].asset_type == AssetType.FII

    def test_catalog_without_etfs(self, tmp_path):
        routes = {
            "https://fiis.com.br/lista-de-fundos-imobiliarios/": fixture_bytes("fiis_lista.html"),
        }
        entries = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch_catalog()
        assert entries and all(e.asset_type == AssetType.FII for e in entries)


QQQI_NAME = "BUENA VISTA NASDAQ-100 NEOS HIGH INCOME ETF INDEX (NDXHIEN) FUNDO DE ÍNDICE"


def qqqi_routes(declared_until: str = "20/10/2026") -> dict[str, bytes]:
    etfs = {
        "page": {"totalRecords": 1, "totalPages": 1},
        "results": [{"acronym": "QQQI", "fundName": QQQI_NAME}],
    }
    rows = [
        ("20/10/2026", "1,08310423", "10/11/2026"),
        ("15/09/2026", "1,11241498", "08/10/2026"),
    ]
    if declared_until == "17/11/2026":
        rows.insert(0, ("17/11/2026", "1,10000000", "08/12/2026"))
    proventos = {
        "cashDividends": [
            {"isinCode": "BRQQQICTF000", "label": "RENDIMENTO", "lastDatePrior": d,
             "rate": v, "paymentDate": p}
            for d, v, p in rows
        ]
    }  # fmt: skip
    return {
        b3.etf_list_url("ETF", 1): json.dumps(etfs).encode(),
        b3.supplement_url("QQQI11"): json.dumps(proventos).encode(),
        buenavista.schedule_url("QQQI11"): fixture_bytes("buenavista_qqqi11.json"),
        f"{b3.BASE_URL}/{b3.cotahist_name(date(2026, 10, 20))}": cotahist(
            date(2026, 10, 20), {"QQQI11": "92.59"}
        ),
        f"{b3.BASE_URL}/{b3.cotahist_name(date(2026, 11, 17))}": cotahist(
            date(2026, 11, 17), {"QQQI11": "93.00"}
        ),
    }


class TestEtfAgenda:
    @pytest.fixture(autouse=True)
    def today(self, monkeypatch):
        monkeypatch.setattr(fetcher_module, "local_today", lambda: date(2026, 11, 12))

    def test_parse_schedule(self):
        rows = buenavista.parse_schedule(fixture_bytes("buenavista_qqqi11.json"), "QQQI11")
        assert [r.datacom for r in rows] == [
            date(2026, 9, 15),
            date(2026, 10, 20),
            date(2026, 11, 17),
            date(2026, 12, 15),
        ]
        assert rows[1].valor == Decimal("1.08310423")
        assert rows[2].valor is None
        assert rows[2].data_pagamento == date(2026, 12, 8)
        assert buenavista.parse_schedule(fixture_bytes("buenavista_qqqi11.json"), "COIN11") == []
        with pytest.raises(ParseError):
            buenavista.parse_schedule(b'{"code": "erro"}', "QQQI11")

    def test_next_datacom_before_value(self, tmp_path):
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(qqqi_routes())).fetch(["QQQI11"])
        data = result.data
        assert result.status == FetchStatus.OK, result.error
        assert data.datacom == date(2026, 11, 17)
        assert data.rendimento is None
        assert data.cotacao_base is None  # data-com ainda não chegou
        assert data.data_pagamento == date(2026, 12, 8)
        assert data.datacom_anterior == date(2026, 10, 20)
        assert data.rendimento_anterior == Decimal("1.08310423")
        assert data.agenda == [date(2026, 11, 17), date(2026, 12, 15)]
        assert data.source_field == "agenda da gestora"

    def test_declared_value_comes_from_b3(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetcher_module, "local_today", lambda: date(2026, 11, 18))
        routes = qqqi_routes(declared_until="17/11/2026")
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["QQQI11"])
        data = result.data
        assert data.datacom == date(2026, 11, 17)
        assert data.rendimento == Decimal("1.10000000")
        assert data.cotacao_base == Decimal("93")
        assert data.source_field == "proventos B3"
        assert data.agenda == [date(2026, 12, 15)]

    def test_schedule_failure_keeps_b3(self, tmp_path):
        routes = qqqi_routes()
        del routes[buenavista.schedule_url("QQQI11")]
        [result] = OfficialFetcher(tmp_path, http=FakeHttp(routes)).fetch(["QQQI11"])
        assert result.data.datacom == date(2026, 10, 20)
        assert result.data.agenda == []

    def test_other_managers_skip_schedule(self, tmp_path):
        http = FakeHttp(etf_routes())
        OfficialFetcher(tmp_path, http=http).fetch(["NDIV11"])
        assert not any("buenavista" in u for u in http.requests)


def test_busca_do_fundosnet_inclui_fiagros():
    # Desde a CVM 175 os Fiagros publicam avisos como tipo de fundo 11, não 1 (FII):
    # filtrar por tipo escondia os rendimentos novos deles.
    url = fundosnet.search_url(CNPJ)
    assert "tipoFundo=&" in url
    assert "tipoFundo=1" not in url
