"""Cotações de fechamento da B3, a partir do arquivo diário COTAHIST.

O arquivo do pregão sai na manhã seguinte e fica em cache no diretório de dados,
então cada dia é baixado uma vez só.
"""

import io
import threading
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from ativos_cli.errors import ParseError
from ativos_cli.scraper.http import Http, HttpStatusError

BASE_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist"
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
