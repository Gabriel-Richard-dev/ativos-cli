from decimal import Decimal

from ativos_cli.models import CatalogEntry, FetchStatus
from ativos_cli.repositories.asset_repository import AssetRepository
from ativos_cli.repositories.database import MIGRATIONS, connect
from tests.conftest import failed_result, ok_result


def test_add_and_no_duplicates(repo):
    assert repo.add_to_wallet("MXRF11", "Maxi Renda") is True
    assert repo.add_to_wallet("MXRF11") is False
    assert repo.wallet_tickers() == ["MXRF11"]


def test_wallet_order_is_insertion_order(repo):
    for ticker in ("KNCR11", "MXRF11", "XPML11"):
        repo.add_to_wallet(ticker)
    assert repo.wallet_tickers() == ["KNCR11", "MXRF11", "XPML11"]


def test_remove_keeps_history(repo, fetcher):
    repo.add_to_wallet("MXRF11")
    repo.save_snapshot(fetcher.results["MXRF11"])
    assert repo.remove_from_wallet("MXRF11") is True
    assert repo.wallet_tickers() == []
    assert repo.count_snapshots("MXRF11") == 1
    assert repo.last_valid("MXRF11") is not None


def test_remove_with_purge_deletes_history(repo, fetcher):
    repo.add_to_wallet("MXRF11")
    repo.save_snapshot(fetcher.results["MXRF11"])
    assert repo.remove_from_wallet("MXRF11", purge=True) is True
    assert repo.count_snapshots("MXRF11") == 0


def test_remove_missing(repo):
    assert repo.remove_from_wallet("MXRF11") is False


def test_snapshot_roundtrip(repo, fetcher):
    saved = repo.save_snapshot(fetcher.results["MXRF11"])
    loaded = repo.last_valid("MXRF11")
    assert loaded == saved
    assert loaded.rendimento == Decimal("0.1")
    assert loaded.cotacao_base == Decimal("9.17")
    assert loaded.datacom.isoformat() == "2026-09-30"
    assert loaded.source_field == "pr_*"


def test_failure_does_not_replace_valid_data(repo, fetcher):
    repo.save_snapshot(fetcher.results["MXRF11"])
    repo.save_snapshot(failed_result("MXRF11"))
    assert repo.last_attempt("MXRF11").status == FetchStatus.ERROR
    valid = repo.last_valid("MXRF11")
    assert valid.status == FetchStatus.OK
    assert valid.rendimento == Decimal("0.1")


def test_history_newest_first(repo, fetcher):
    repo.save_snapshot(fetcher.results["MXRF11"])
    repo.save_snapshot(failed_result("MXRF11"))
    statuses = [s.status for s in repo.history("MXRF11")]
    assert statuses == [FetchStatus.ERROR, FetchStatus.OK]


def test_data_persists_after_reopening(tmp_path, fetcher):
    path = tmp_path / "sub" / "dir" / "ativos.db"
    first = AssetRepository(connect(path))
    first.add_to_wallet("MXRF11")
    first.save_snapshot(fetcher.results["MXRF11"])
    first.conn.close()

    second = AssetRepository(connect(path))
    assert second.wallet_tickers() == ["MXRF11"]
    assert second.last_valid("MXRF11").rendimento == Decimal("0.1")
    assert second.get_name("MXRF11") == "Maxi Renda"


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "ativos.db"
    connect(path).close()
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_catalog_keeps_validation_mark(repo):
    repo.mark_validated("MXRF11", "Maxi Renda")
    repo.replace_catalog([CatalogEntry(ticker="MXRF11", name="Maxi Renda FII")])
    entry = repo.get_catalog_entry("MXRF11")
    assert entry.name == "Maxi Renda FII"
    assert entry.validated_at is not None
    assert repo.catalog_updated_at() is not None


def test_known_but_not_validated(repo):
    repo.replace_catalog([CatalogEntry(ticker="KNCR11", name="Kinea")])
    assert repo.get_catalog_entry("KNCR11").validated_at is None


def test_name_falls_back_to_catalog(repo):
    repo.replace_catalog([CatalogEntry(ticker="KNCR11", name="Kinea")])
    assert repo.get_name("KNCR11") == "Kinea"


def test_snapshot_without_name_keeps_previous_name(repo, fetcher):
    repo.save_snapshot(fetcher.results["MXRF11"])
    repo.save_snapshot(ok_result("MXRF11").model_copy(update={"data": None}))
    assert repo.get_name("MXRF11") == "Maxi Renda"
