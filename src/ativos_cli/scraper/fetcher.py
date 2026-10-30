"""Coleta dos dados de cada FII a partir das fontes oficiais.

Para cada ticker:
1. CNPJ e nome, uma única vez por fundo (fica em cache): página do fundo no
   fiis.com.br; se ela não existir, cadastro da CVM pelo ISIN e, para fundos que
   mudaram de ticker, pelo nome oficial informado pela B3. O aviso do FundosNet
   confirma: ele precisa trazer o ticker procurado.
2. Data-com, valor e pagamento: último aviso de rendimentos no FundosNet (B3).
   Avisos publicados não mudam, então cada um é lido uma vez e fica em cache; numa
   atualização com cache, sobra uma requisição (a busca) por fundo.
3. Cotação-base: fechamento da data-com no arquivo COTAHIST da B3 (cache por dia), o
   mesmo que o Status Invest mostra. Enquanto o arquivo do dia não sai (manhã
   seguinte), usa a cotação-base e o Rend. % do card de rendimento do Status Invest;
   sem o card (Chrome indisponível, site bloqueando), a cotação do momento da B3,
   marcada como provisória. O Rend. % é o valor dividido pela cotação-base, cortado
   em 4 casas (como o Status Invest).

Os tickers são consultados em paralelo (até `config.PARALLEL_REQUESTS`); dentro de
cada ticker as etapas são sequenciais, porque cada uma depende da anterior.
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from decimal import Decimal
from pathlib import Path

from ativos_cli import config
from ativos_cli.errors import AtivosError
from ativos_cli.models import CatalogEntry, FetchResult, FetchStatus, FundData, FundIdentity
from ativos_cli.scraper import b3, cvm, fundosnet, statusinvest
from ativos_cli.scraper.b3 import ClosingPrices
from ativos_cli.scraper.http import Http, HttpStatusError
from ativos_cli.scraper.parser import parse_catalog, parse_fund_identity
from ativos_cli.services import ResultCallback
from ativos_cli.utils.dates import now_utc
from ativos_cli.utils.money import truncate, yield_percent

log = logging.getLogger(__name__)

YIELD_PLACES = 4


class JsonCache:
    """Dicionário persistido num arquivo JSON, seguro entre threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        try:
            self._data: dict = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def get(self, key: str):
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)


class OfficialFetcher:
    def __init__(
        self,
        cache_dir: Path,
        http: Http | None = None,
        browser: statusinvest.Browser | None = None,
    ) -> None:
        self.http = http or Http()
        # Sem navegador, a cotação-base vem só da B3.
        self.browser = browser
        self.prices = ClosingPrices(self.http, cache_dir / "cotahist")
        self.identities = JsonCache(cache_dir / "fundos.json")
        self.notices = JsonCache(cache_dir / "avisos.json")
        self.cards = JsonCache(cache_dir / "statusinvest.json")
        self.registry = cvm.Registry(self.http, cache_dir / "cvm")

    # --- Fetcher ---------------------------------------------------------------

    def fetch(
        self, tickers: list[str], on_result: ResultCallback | None = None
    ) -> list[FetchResult]:
        results: dict[str, FetchResult] = {}
        try:
            with ThreadPoolExecutor(max_workers=config.PARALLEL_REQUESTS) as pool:
                futures = [pool.submit(self._fetch_one, t) for t in dict.fromkeys(tickers)]
                for future in as_completed(futures):
                    result = future.result()
                    results[result.ticker] = result
                    if on_result:
                        on_result(result)
        finally:
            if self.browser:
                self.browser.close()
        return [results[t] for t in tickers]

    def fetch_catalog(self) -> list[CatalogEntry]:
        return parse_catalog(self.http.get(config.CATALOG_URL).decode("utf-8", "replace"))

    # --- um ticker -------------------------------------------------------------

    def _fetch_one(self, ticker: str) -> FetchResult:
        result = FetchResult(
            ticker=ticker,
            status=FetchStatus.ERROR,
            source_url=config.fund_url(ticker),
            fetched_at=now_utc(),
        )
        try:
            identity = self._identity(ticker)
        except HttpStatusError as exc:
            if exc.status == 404:
                result.status = FetchStatus.NOT_FOUND
                result.error = f"Ativo {ticker} não encontrado."
            else:
                result.error = str(exc)
            return result
        except AtivosError as exc:
            result.error = str(exc)
            return result

        try:
            result.data = self._fund_data(identity)
        except AtivosError as exc:
            result.error = str(exc)
            return result
        except Exception as exc:  # nunca derruba a coleta dos outros tickers
            log.debug("Falha inesperada em %s", ticker, exc_info=True)
            result.error = f"Falha inesperada: {exc}"
            return result

        result.status = FetchStatus.OK
        result.source_url = fundosnet.search_page_url(identity.cnpj)
        if result.data.source_field:
            notice_id = int(result.data.source_field.rsplit(" ", 1)[-1])
            result.source_url = fundosnet.notice_page_url(notice_id)
        return result

    def _identity(self, ticker: str) -> FundIdentity:
        cached = self.identities.get(ticker)
        if cached:
            return FundIdentity.model_validate(cached)
        try:
            page = self.http.get(config.fund_url(ticker)).decode("utf-8", "replace")
            identity = parse_fund_identity(page, expected_ticker=ticker)
        except HttpStatusError as exc:
            if exc.status != 404:
                raise
            identity = self._registered_identity(ticker)
            if identity is None:
                raise
        self.identities.set(ticker, identity.model_dump())
        return identity

    def _registered_identity(self, ticker: str) -> FundIdentity | None:
        """CNPJ pelo cadastro da CVM: primeiro pelo ISIN, depois pelo nome na B3."""
        fund = self.registry.by_ticker(ticker)
        if fund is None:
            name = b3.parse_fund_name(self.http.get(b3.funds_search_url(ticker)), ticker)
            fund = self.registry.by_name(name) if name else None
        if fund is None:
            return None
        return FundIdentity(ticker=ticker, name=fund.name, cnpj=fund.cnpj)

    def _fund_data(self, identity: FundIdentity) -> FundData:
        data = FundData(ticker=identity.ticker, name=identity.name)
        dividend = self._latest_dividend(identity)
        if dividend is None:
            data.notes.append("Nenhum aviso de rendimentos encontrado no FundosNet.")
            return data
        data.datacom = dividend.datacom
        data.rendimento = dividend.valor
        data.data_pagamento = dividend.data_pagamento
        data.source_field = f"aviso {dividend.notice_id}"
        data.cotacao_base = self.prices.close(identity.ticker, dividend.datacom)
        if data.cotacao_base is None:
            # Fechamento oficial ainda não publicado: o Status Invest já tem o do pregão.
            if card := self._status_invest_card(identity.ticker, dividend.datacom):
                data.cotacao_base = card.cotacao_base
                data.rendimento_pct = card.rendimento_pct
                return data
            data.cotacao_base = self._current_price(identity.ticker)
            data.cotacao_provisoria = data.cotacao_base is not None
        data.rendimento_pct = truncate(
            yield_percent(dividend.valor, data.cotacao_base), YIELD_PLACES
        )
        return data

    def _status_invest_card(self, ticker: str, datacom: date) -> statusinvest.Card | None:
        """Card do Status Invest com a mesma data-com e cotação-base, se houver.

        Passada a data-com, a cotação-base dela não muda: o card fica em cache e o Chrome
        só abre para rendimentos novos (ou do dia).
        """
        key = f"{ticker}:{datacom.isoformat()}"
        if cached := self.cards.get(key):
            return statusinvest.Card(
                rendimento=None,
                rendimento_pct=Decimal(cached["rendimento_pct"]),
                cotacao_base=Decimal(cached["cotacao_base"]),
                datacom=datacom,
                data_pagamento=None,
            )
        if self.browser is None:
            return None
        try:
            cards = statusinvest.parse_cards(self.browser.get(statusinvest.page_url(ticker)))
        except AtivosError as exc:
            log.debug("Status Invest indisponível para %s: %s", ticker, exc)
            return None
        for card in cards:
            if card.datacom == datacom and card.cotacao_base and card.rendimento_pct:
                if datacom < date.today():
                    self.cards.set(
                        key,
                        {
                            "cotacao_base": str(card.cotacao_base),
                            "rendimento_pct": str(card.rendimento_pct),
                        },
                    )
                return card
        return None

    def _current_price(self, ticker: str):
        """Cotação do momento na B3; sem ela, a cotação-base fica em branco por ora."""
        try:
            return b3.parse_quote(self.http.get(b3.quote_url(ticker)), ticker)
        except AtivosError as exc:
            log.debug("Cotação provisória de %s indisponível: %s", ticker, exc)
            return None

    def _latest_dividend(self, identity: FundIdentity) -> fundosnet.Dividend | None:
        notices = fundosnet.parse_search(
            self.http.get(
                fundosnet.search_url(identity.cnpj), {"X-Requested-With": "XMLHttpRequest"}
            )
        )
        # A busca vem do aviso mais novo para o mais antigo: o primeiro com rendimento
        # para o ticker é o atual, e os demais nem precisam ser baixados.
        for notice in notices:
            if (dividend := self._notice_dividend(notice.id, identity.ticker)) is not None:
                return dividend
        return None

    def _notice_dividend(self, notice_id: int, ticker: str) -> fundosnet.Dividend | None:
        key = f"{notice_id}:{ticker}"
        cached = self.notices.get(key)
        if cached is not None:
            return fundosnet.Dividend.from_dict(cached) if cached else None
        dividend = fundosnet.parse_notice(
            self.http.get(fundosnet.document_url(notice_id)), ticker, notice_id
        )
        # {} marca "aviso sem rendimento para este ticker", para não baixar de novo.
        self.notices.set(key, dividend.to_dict() if dividend else {})
        return dividend
