"""Pesquisa aproximada por ticker e nome no catálogo local."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from ativos_cli import config
from ativos_cli.models import CatalogEntry
from ativos_cli.repositories.asset_repository import AssetRepository
from ativos_cli.services import Fetcher
from ativos_cli.utils.dates import now_utc

# Cada palavra do termo precisa se parecer com alguma palavra do nome.
MIN_WORD_RATIO = 0.7
MIN_TICKER_RATIO = 0.75


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, só letras/dígitos separados por espaço."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


@dataclass
class SearchHit:
    entry: CatalogEntry
    score: float


@dataclass
class CatalogStatus:
    count: int
    updated_at: datetime | None

    @property
    def missing(self) -> bool:
        return self.count == 0

    @property
    def partial(self) -> bool:
        """Só há os ativos já consultados; o catálogo completo nunca foi baixado."""
        return self.count > 0 and self.updated_at is None

    @property
    def stale(self) -> bool:
        return self.updated_at is not None and (
            now_utc() - self.updated_at > config.CATALOG_STALE_AFTER
        )


def score(term: str, entry: CatalogEntry) -> float:
    """Relevância de 0 a 100. `term` já deve estar normalizado."""
    compact = term.replace(" ", "")
    ticker = entry.ticker.lower()
    name = normalize(entry.name)

    if compact == ticker:
        return 100
    if ticker.startswith(compact):
        return 90
    if len(compact) >= 3 and compact in ticker:
        return 75
    if name == term:
        return 85
    if name.startswith(term):
        return 80
    if f" {term}" in f" {name}":
        return 70

    name_words = name.split()
    term_words = term.split()
    if term_words and all(any(w.startswith(t) for w in name_words) for t in term_words):
        return 65

    # Tolerância a erros de digitação: cada palavra do termo contra a melhor palavra do nome.
    ratios = [
        max((SequenceMatcher(None, t, w).ratio() for w in name_words), default=0)
        for t in term_words
    ]
    words = sum(ratios) / len(ratios) if ratios and min(ratios) >= MIN_WORD_RATIO else 0
    tick = SequenceMatcher(None, compact, ticker).ratio()
    tick = tick if tick >= MIN_TICKER_RATIO else 0
    return round(max(words, tick) * 60, 1)


def rank(raw_term: str, entries: list[CatalogEntry], limit: int = 15) -> list[SearchHit]:
    """Ordena `entries` por relevância para o termo (sem acessar o banco)."""
    term = normalize(raw_term)
    if not term:
        return []
    hits = [SearchHit(e, s) for e in entries if (s := score(term, e)) > 0]
    hits.sort(key=lambda h: (-h.score, h.entry.ticker))
    return hits[:limit]


class SearchService:
    def __init__(self, repo: AssetRepository, fetcher: Fetcher) -> None:
        self.repo = repo
        self.fetcher = fetcher

    def status(self) -> CatalogStatus:
        return CatalogStatus(
            count=len(self.repo.list_catalog()), updated_at=self.repo.catalog_updated_at()
        )

    def update_catalog(self) -> int:
        entries = self.fetcher.fetch_catalog()
        self.repo.replace_catalog(entries)
        return len(entries)

    def search(self, raw_term: str, limit: int = 15) -> list[SearchHit]:
        return rank(raw_term, self.repo.list_catalog(), limit)
