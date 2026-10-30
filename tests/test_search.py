import pytest

from ativos_cli.models import CatalogEntry
from ativos_cli.services.search_service import normalize, score


@pytest.fixture
def loaded(search):
    search.update_catalog()
    return search


def tickers(hits):
    return [h.entry.ticker for h in hits]


def test_normalize():
    assert normalize("  Índice de PREÇOS! ") == "indice de precos"


@pytest.mark.parametrize(
    ("term", "expected_first"),
    [
        ("mxrf", "MXRF11"),
        ("MXRF11", "MXRF11"),
        ("maxi renda", "MXRF11"),
        ("Maxi", "MXRF11"),
        ("kncr", "KNCR11"),
        ("kinea rendimentos", "KNCR11"),
        ("kinea rendimetos", "KNCR11"),  # erro de digitação
        ("xp malls", "XPML11"),
        ("índice de preços", "KNIP11"),
    ],
)
def test_relevant_first(loaded, term, expected_first):
    assert tickers(loaded.search(term))[0] == expected_first


def test_exact_ticker_beats_name(loaded):
    hits = loaded.search("kncr11")
    assert hits[0].score == 100


def test_unrelated_words_do_not_match(loaded):
    assert "CXTL11" not in tickers(loaded.search("maxi renda"))


def test_no_results(loaded):
    assert loaded.search("zzzzzzzz") == []
    assert loaded.search("   ") == []


def test_limit(loaded):
    assert len(loaded.search("fundo", limit=5)) <= 5


def test_status(search):
    assert search.status().missing
    search.update_catalog()
    status = search.status()
    assert status.count > 500
    assert not status.missing and not status.stale and not status.partial


def test_partial_catalog(search, service):
    service.lookup("MXRF11")
    assert search.status().partial
    assert tickers(search.search("maxi")) == ["MXRF11"]


def test_score_ordering():
    entry = CatalogEntry(ticker="MXRF11", name="Maxi Renda")
    assert score("mxrf11", entry) > score("mxrf", entry) > score("maxi renda", entry)
    assert score("shopping", entry) == 0
