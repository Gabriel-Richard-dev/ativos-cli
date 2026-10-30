"""Cadastro de FIIs nos dados abertos da CVM (informe mensal, arquivo "geral").

Usado para achar o CNPJ de um fundo quando o fiis.com.br não tem a página dele:
- pelo código do ISIN (BRMXRFCTF008 -> MXRF11), ou
- pelo nome oficial do fundo (informado pela B3), para fundos que mudaram de ticker
  e continuam com o ISIN antigo na CVM.
"""

import csv
import io
import re
import threading
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ativos_cli.errors import ParseError
from ativos_cli.scraper.http import Http, HttpStatusError

BASE_URL = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS"
# O informe é mensal; baixar de novo uma vez por semana basta para fundos novos.
REFRESH_SECONDS = 7 * 24 * 3600
# Termos que variam entre a B3 e a CVM para o mesmo fundo.
_NAME_NOISE = re.compile(
    r"\b(RESPONSABILIDADE LIMITADA|FUNDO DE INVESTIMENTO IMOBILIARIO|FII|RL|CLASSE UNICA)\b"
)


@dataclass(frozen=True)
class RegisteredFund:
    cnpj: str
    name: str
    isin: str


def file_name(year: int) -> str:
    return f"inf_mensal_fii_{year}.zip"


def normalize_name(name: str) -> str:
    """Nome comparável: sem acentos, pontuação e termos genéricos."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    return " ".join(_NAME_NOISE.sub(" ", text).split())


def parse_registry(payload: bytes) -> list[RegisteredFund]:
    """Um registro por CNPJ, com o nome e o ISIN do informe mais recente."""
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            name = next(n for n in archive.namelist() if "geral" in n)
            text = archive.read(name).decode("latin-1")
    except (zipfile.BadZipFile, StopIteration) as exc:
        raise ParseError("Cadastro de fundos da CVM em formato inesperado.") from exc
    latest: dict[str, tuple[str, RegisteredFund]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        cnpj = re.sub(r"\D", "", row.get("CNPJ_Fundo_Classe") or "")
        if len(cnpj) != 14:
            continue
        when = row.get("Data_Referencia") or ""
        fund = RegisteredFund(
            cnpj=cnpj,
            name=(row.get("Nome_Fundo_Classe") or "").strip(),
            isin=(row.get("Codigo_ISIN") or "").strip().upper(),
        )
        if cnpj not in latest or when >= latest[cnpj][0]:
            latest[cnpj] = (when, fund)
    return [fund for _, fund in latest.values()]


class Registry:
    """Cadastro da CVM com cache em disco, carregado uma vez por execução."""

    def __init__(self, http: Http, cache_dir: Path) -> None:
        self.http = http
        self.cache_dir = cache_dir
        self._funds: list[RegisteredFund] | None = None
        self._lock = threading.Lock()

    def by_ticker(self, ticker: str) -> RegisteredFund | None:
        code = ticker[:4]
        matches = [f for f in self.funds() if f.isin[2:6] == code]
        return matches[0] if len(matches) == 1 else None

    def by_name(self, name: str) -> RegisteredFund | None:
        wanted = normalize_name(name)
        if len(wanted) < 6:
            return None
        matches = [f for f in self.funds() if normalize_name(f.name) == wanted]
        return matches[0] if len(matches) == 1 else None

    def funds(self) -> list[RegisteredFund]:
        with self._lock:
            if self._funds is None:
                self._funds = self._load()
            return self._funds

    def _load(self) -> list[RegisteredFund]:
        year = date.today().year
        for candidate in (year, year - 1):  # em janeiro o arquivo do ano pode não existir
            path = self.cache_dir / file_name(candidate)
            fresh = path.exists() and time.time() - path.stat().st_mtime < REFRESH_SECONDS
            if not fresh:
                try:
                    payload = self.http.get(f"{BASE_URL}/{file_name(candidate)}")
                except HttpStatusError as exc:
                    if exc.status == 404 and not path.exists():
                        continue
                    if not path.exists():
                        raise
                else:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
            return parse_registry(path.read_bytes())
        return []
