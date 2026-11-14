"""Cotações da B3.

- Fechamento oficial: arquivo diário COTAHIST. O arquivo do pregão sai na manhã
  seguinte e fica em cache no diretório de dados, então cada dia é baixado uma vez.
- Cotação do momento (com atraso de 15 minutos): serviço público de cotações da B3,
  usado como cotação-base provisória enquanto o COTAHIST do dia não sai.
- ETFs: a lista de fundos de índice listados e os proventos em dinheiro de cada um
  (os ETFs não publicam avisos estruturados no FundosNet, como os FIIs).
"""

import base64
import io
import json
import threading
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from ativos_cli.errors import ParseError
from ativos_cli.scraper.http import Http, HttpStatusError
from ativos_cli.utils.dates import parse_date
from ativos_cli.utils.money import to_decimal

BASE_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist"
QUOTE_URL = "https://cotacao.b3.com.br/mds/api/v1/instrumentQuotation"
FUNDS_URL = "https://sistemaswebb3-listados.b3.com.br/fundsListedProxy/Search/GetListFunds"
SUPPLEMENT_URL = (
    "https://sistemaswebb3-listados.b3.com.br/fundsProxy/fundsCall/GetListedSupplementFunds"
)
# Categorias de ETF na B3: ações, renda fixa e fundos imobiliários.
ETF_TYPES = ("ETF", "ETF-RF", "ETF-FII")
# A B3 recusa páginas maiores que isso (responde lista vazia).
ETF_PAGE_SIZE = 100
# Código de "fundos" no serviço de proventos (vale para ETFs e FIIs).
SUPPLEMENT_FUND_TYPE = 7
# Mercado à vista: é onde as cotas de FII são negociadas.
SPOT_MARKET = "010"
# Mercados aceitos na cotação do momento: FIIs aparecem como "Vista", ETFs como "ETF"
# e ETFs de renda fixa (ex.: IMAB11) como "RendaFixaPrivada".
QUOTE_MARKETS = {"Vista", "ETF", "RendaFixaPrivada"}


def cotahist_name(day: date) -> str:
    return f"COTAHIST_D{day:%d%m%Y}.ZIP"


def parse_cotahist(payload: bytes) -> dict[str, Decimal]:
    """Preço de fechamento (PREULT) de cada ticker no mercado à vista.

    Layout de posições fixas publicado pela B3: CODNEG nas colunas 13-24, TPMERC em
    25-27 e PREULT em 109-121 (inteiro com 2 casas decimais implícitas).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            text = archive.read(archive.namelist()[0]).decode("latin-1")
    except (zipfile.BadZipFile, IndexError) as exc:
        raise ParseError("Arquivo de cotações da B3 inválido.") from exc
    closes = {}
    for line in text.splitlines():
        if line[:2] != "01" or line[24:27] != SPOT_MARKET:
            continue
        closes[line[12:24].strip()] = Decimal(int(line[108:121])) / 100
    return closes


def funds_search_url(ticker: str) -> str:
    query = {"language": "pt-br", "pageNumber": 1, "pageSize": 20}
    query |= {"keyword": ticker[:4], "typeFund": "FII"}
    return f"{FUNDS_URL}/{base64.b64encode(json.dumps(query).encode()).decode()}"


def parse_fund_name(payload: bytes, ticker: str) -> str | None:
    """Nome oficial do FII listado com o código do ticker (as 4 letras), se houver."""
    try:
        results = json.loads(payload).get("results") or []
    except (ValueError, AttributeError) as exc:
        raise ParseError("Resposta inesperada da busca de fundos da B3.") from exc
    for fund in results:
        if (fund.get("acronym") or "").upper() == ticker[:4]:
            return fund.get("fundName") or None
    return None


def _encode(query: dict) -> str:
    return base64.b64encode(json.dumps(query).encode()).decode()


def etf_list_url(etf_type: str, page: int) -> str:
    query = {"language": "pt-br", "pageNumber": page, "pageSize": ETF_PAGE_SIZE}
    return f"{FUNDS_URL}/{_encode(query | {'keyword': '', 'typeFund': etf_type})}"


def parse_etf_list(payload: bytes) -> tuple[dict[str, str], int]:
    """Tickers (código + "11") e nomes de uma página da lista, e o total de páginas.

    A B3 às vezes responde "0 registros" por engano; quem chama tenta de novo.
    """
    try:
        data = json.loads(payload)
        pages = int((data.get("page") or {}).get("totalPages") or 0)
        results = data.get("results") or []
    except (ValueError, AttributeError, TypeError) as exc:
        raise ParseError("Resposta inesperada da lista de ETFs da B3.") from exc
    etfs = {}
    for fund in results:
        code = (fund.get("acronym") or "").strip().upper()
        if len(code) != 4:
            continue
        name = " ".join((fund.get("fundName") or fund.get("tradingName") or code).split())
        etfs[f"{code}11"] = name
    return etfs, pages


@dataclass(frozen=True)
class Distribution:
    """Provento em dinheiro de um ETF: data-com, valor por cota e pagamento."""

    datacom: date
    valor: Decimal
    data_pagamento: date | None


def supplement_url(ticker: str) -> str:
    query = {"cnpj": "0", "identifierFund": ticker[:4], "typeFund": SUPPLEMENT_FUND_TYPE}
    return f"{SUPPLEMENT_URL}/{_encode(query)}"


def parse_distributions(payload: bytes, ticker: str) -> list[Distribution]:
    """Proventos em dinheiro do ticker, da data-com mais nova para a mais antiga.

    Amortizações ficam de fora. Proventos com a mesma data-com são somados. A B3 responde
    vazio para fundos sem cadastro de proventos (ex.: ETFs de renda fixa): lista vazia.
    """
    if not payload.strip():
        return []
    try:
        rows = json.loads(payload).get("cashDividends") or []
    except (ValueError, AttributeError) as exc:
        raise ParseError("Resposta inesperada dos proventos da B3.") from exc
    by_date: dict[date, Distribution] = {}
    for row in rows:
        isin = (row.get("isinCode") or row.get("assetIssued") or "").upper()
        if isin[2:6] != ticker[:4] or "AMORT" in (row.get("label") or "").upper():
            continue
        datacom = parse_date(row.get("lastDatePrior"))
        valor = to_decimal(row.get("rate"))
        if datacom is None or valor is None:
            continue
        previous = by_date.get(datacom)
        by_date[datacom] = Distribution(
            datacom=datacom,
            valor=valor + (previous.valor if previous else 0),
            data_pagamento=parse_date(row.get("paymentDate"))
            or (previous.data_pagamento if previous else None),
        )
    return sorted(by_date.values(), key=lambda d: d.datacom, reverse=True)


def quote_url(ticker: str) -> str:
    return f"{QUOTE_URL}/{ticker}"


@dataclass(frozen=True)
class Quote:
    """Cotação do momento: último preço e variação do dia em % (`prcFlcn`)."""

    price: Decimal
    change_pct: Decimal | None = None


def parse_quote(payload: bytes, ticker: str) -> Decimal | None:
    """Último preço (`curPrc`) do ticker à vista (ou ETF), ou None sem negócios."""
    quote = parse_quote_detail(payload, ticker)
    return quote.price if quote else None


def parse_quote_detail(payload: bytes, ticker: str) -> Quote | None:
    """Último preço e variação do dia do ticker à vista (ou ETF), ou None sem negócios."""
    try:
        trades = json.loads(payload, parse_float=Decimal).get("Trad") or []
    except (ValueError, AttributeError) as exc:
        raise ParseError("Resposta inesperada do serviço de cotações da B3.") from exc
    for trade in trades:
        security = trade.get("scty") or {}
        market = (security.get("mkt") or {}).get("nm")
        if security.get("symb") != ticker or market not in QUOTE_MARKETS:
            continue
        quotation = security.get("SctyQtn") or {}
        price = quotation.get("curPrc")
        if isinstance(price, (int, Decimal)) and price > 0:
            change = quotation.get("prcFlcn")
            valid_change = isinstance(change, (int, Decimal)) and not isinstance(change, bool)
            return Quote(Decimal(price), Decimal(change) if valid_change else None)
    return None


class ClosingPrices:
    """Fechamentos por dia, com cache em disco (arquivo) e em memória (já lido)."""

    def __init__(self, http: Http, cache_dir: Path) -> None:
        self.http = http
        self.cache_dir = cache_dir
        self._days: dict[date, dict[str, Decimal] | None] = {}
        self._locks: dict[date, threading.Lock] = {}
        self._guard = threading.Lock()

    def close(self, ticker: str, day: date) -> Decimal | None:
        """Fechamento do ticker no dia, ou None se o arquivo do dia ainda não saiu."""
        prices = self._load(day)
        return prices.get(ticker) if prices else None

    def _load(self, day: date) -> dict[str, Decimal] | None:
        with self._guard:
            lock = self._locks.setdefault(day, threading.Lock())
        with lock:  # várias threads pedindo o mesmo dia baixam o arquivo uma vez
            if day not in self._days:
                self._days[day] = self._read(day)
            return self._days[day]

    def _read(self, day: date) -> dict[str, Decimal] | None:
        path = self.cache_dir / cotahist_name(day)
        if path.exists():
            return parse_cotahist(path.read_bytes())
        try:
            payload = self.http.get(f"{BASE_URL}/{cotahist_name(day)}")
        except HttpStatusError as exc:
            if exc.status == 404:  # pregão de hoje, ainda não publicado
                return None
            raise
        prices = parse_cotahist(payload)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return prices
