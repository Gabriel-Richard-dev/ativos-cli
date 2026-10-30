"""Cotações da B3.

- Fechamento oficial: arquivo diário COTAHIST. O arquivo do pregão sai na manhã
  seguinte e fica em cache no diretório de dados, então cada dia é baixado uma vez.
- Cotação do momento (com atraso de 15 minutos): serviço público de cotações da B3,
  usado como cotação-base provisória enquanto o COTAHIST do dia não sai.
"""

import base64
import io
import json
import threading
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from ativos_cli.errors import ParseError
from ativos_cli.scraper.http import Http, HttpStatusError

BASE_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist"
QUOTE_URL = "https://cotacao.b3.com.br/mds/api/v1/instrumentQuotation"
FUNDS_URL = "https://sistemaswebb3-listados.b3.com.br/fundsListedProxy/Search/GetListFunds"
# Mercado à vista: é onde as cotas de FII são negociadas.
SPOT_MARKET = "010"


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


def quote_url(ticker: str) -> str:
    return f"{QUOTE_URL}/{ticker}"


def parse_quote(payload: bytes, ticker: str) -> Decimal | None:
    """Último preço (`curPrc`) do ticker no mercado à vista, ou None sem negócios."""
    try:
        trades = json.loads(payload, parse_float=Decimal).get("Trad") or []
    except (ValueError, AttributeError) as exc:
        raise ParseError("Resposta inesperada do serviço de cotações da B3.") from exc
    for trade in trades:
        security = trade.get("scty") or {}
        if security.get("symb") != ticker or (security.get("mkt") or {}).get("nm") != "Vista":
            continue
        price = (security.get("SctyQtn") or {}).get("curPrc")
        if isinstance(price, (int, Decimal)) and price > 0:
            return Decimal(price)
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
