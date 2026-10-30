"""Coleta dos dados de cada FII a partir das fontes oficiais.

Para cada ticker:
1. CNPJ e nome: página do fundo no fiis.com.br, uma única vez (fica em cache).
2. Data-com, valor e pagamento: último aviso de rendimentos no FundosNet (B3).
   Avisos publicados não mudam, então cada um é lido uma vez e fica em cache; numa
   atualização com cache, sobra uma requisição (a busca) por fundo.
3. Cotação-base: fechamento da data-com no arquivo COTAHIST da B3 (cache por dia).
   O Rend. % é o valor dividido pela cotação-base, cortado em 3 casas.

Os tickers são consultados em paralelo (até `config.PARALLEL_REQUESTS`); dentro de
cada ticker as etapas são sequenciais, porque cada uma depende da anterior.
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ativos_cli import config
from ativos_cli.errors import AtivosError
from ativos_cli.models import CatalogEntry, FetchResult, FetchStatus, FundData, FundIdentity
from ativos_cli.scraper import fundosnet
from ativos_cli.scraper.b3 import ClosingPrices
from ativos_cli.scraper.http import Http, HttpStatusError
from ativos_cli.scraper.parser import parse_catalog, parse_fund_identity
from ativos_cli.services import ResultCallback
from ativos_cli.utils.dates import now_utc
from ativos_cli.utils.money import truncate, yield_percent

log = logging.getLogger(__name__)

YIELD_PLACES = 3


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
    def __init__(self, cache_dir: Path, http: Http | None = None) -> None:
        self.http = http or Http()
        self.prices = ClosingPrices(self.http, cache_dir / "cotahist")
        self.identities = JsonCache(cache_dir / "fundos.json")
        self.notices = JsonCache(cache_dir / "avisos.json")

    # --- Fetcher ---------------------------------------------------------------

    def fetch(
        self, tickers: list[str], on_result: ResultCallback | None = None
    ) -> list[FetchResult]:
        results: dict[str, FetchResult] = {}
        with ThreadPoolExecutor(max_workers=config.PARALLEL_REQUESTS) as pool:
            futures = [pool.submit(self._fetch_one, t) for t in dict.fromkeys(tickers)]
            for future in as_completed(futures):
                result = future.result()
                results[result.ticker] = result
                if on_result:
                    on_result(result)
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
        page = self.http.get(config.fund_url(ticker)).decode("utf-8", "replace")
        identity = parse_fund_identity(page, expected_ticker=ticker)
        self.identities.set(ticker, identity.model_dump())
        return identity

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
        data.rendimento_pct = truncate(
            yield_percent(dividend.valor, data.cotacao_base), YIELD_PLACES
        )
        return data

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
