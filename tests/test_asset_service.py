from datetime import timedelta

import pytest

from ativos_cli.errors import AssetNotFoundError, FetchError, InvalidTickerError
from ativos_cli.models import CatalogEntry, DisplayStatus
from tests.conftest import failed_result, ok_result


def test_lookup_updates_and_validates(service, repo):
    view = service.lookup(" mxrf11 ")
    assert view.ticker == "MXRF11"
    assert view.status == DisplayStatus.UPDATED
    assert view.valid.cotacao_base is not None
    assert repo.get_catalog_entry("MXRF11").validated_at is not None


def test_lookup_invalid_ticker(service, fetcher):
    with pytest.raises(InvalidTickerError):
        service.lookup("MXRF")
    assert fetcher.calls == []


def test_lookup_not_found(service):
    with pytest.raises(AssetNotFoundError):
        service.lookup("ZZZZ11")


def test_lookup_failure_without_cache(service, fetcher):
    fetcher.results["MXRF11"] = failed_result("MXRF11")
    with pytest.raises(FetchError, match="Tempo esgotado"):
        service.lookup("MXRF11")


def test_lookup_failure_falls_back_to_cache(service, fetcher):
    service.lookup("MXRF11")
    fetcher.results["MXRF11"] = failed_result("MXRF11")
    view = service.lookup("MXRF11")
    assert view.status == DisplayStatus.CACHED
    assert view.last_error == "Tempo esgotado ao consultar."
    assert view.valid.rendimento is not None


def test_cache_read_is_never_marked_updated(service):
    service.lookup("MXRF11")
    assert service.view("MXRF11").status == DisplayStatus.CACHED


def test_stale_cache(service, repo):
    repo.save_snapshot(ok_result("MXRF11", age=timedelta(days=3)))
    view = service.view("MXRF11")
    assert view.status == DisplayStatus.CACHED
    assert view.stale is True


def test_never_fetched(service):
    assert service.view("MXRF11").status == DisplayStatus.NO_DATA


def test_refresh_partial_failure(service, fetcher, repo):
    for ticker in ("MXRF11", "KNCR11", "XPML11"):
        repo.add_to_wallet(ticker)
    service.lookup("KNCR11")
    fetcher.results["KNCR11"] = failed_result("KNCR11")
    fetcher.results["XPML11"] = failed_result("XPML11", error="O site está com problemas.")

    progress = []
    summary = service.refresh(on_progress=lambda r: progress.append(r.ticker))

    assert progress == ["MXRF11", "KNCR11", "XPML11"]
    statuses = {v.ticker: v.status for v in summary.views}
    assert statuses == {
        "MXRF11": DisplayStatus.UPDATED,
        "KNCR11": DisplayStatus.CACHED,
        "XPML11": DisplayStatus.FAILED,
    }
    assert [v.ticker for v in summary.failed] == ["KNCR11", "XPML11"]


def test_refresh_single_ticker(service, fetcher, repo):
    repo.add_to_wallet("MXRF11")
    repo.add_to_wallet("KNCR11")
    service.refresh(["kncr11"])
    assert fetcher.calls == [["KNCR11"]]


def test_add_validates_and_avoids_duplicates(service, fetcher):
    first = service.add("MXRF11")
    second = service.add("mxrf11")
    assert first.added is True
    assert first.view.in_wallet is True
    assert second.added is False
    assert service.repo.wallet_tickers() == ["MXRF11"]


def test_add_uses_cache_without_refetching(service, fetcher):
    service.lookup("MXRF11")
    fetcher.calls.clear()
    service.add("MXRF11")
    assert fetcher.calls == []


def test_add_not_found(service):
    with pytest.raises(AssetNotFoundError):
        service.add("ZZZZ11")
    assert service.repo.wallet_tickers() == []


def test_add_offline_known_asset_warns(service, fetcher, repo):
    repo.replace_catalog([CatalogEntry(ticker="XPML11", name="XP Malls")])
    fetcher.results["XPML11"] = failed_result("XPML11")
    outcome = service.add("XPML11")
    assert outcome.added is True
    assert outcome.warning
    assert outcome.view.status == DisplayStatus.FAILED


def test_add_offline_unknown_asset_fails(service, fetcher):
    fetcher.results["XPML11"] = failed_result("XPML11")
    with pytest.raises(FetchError):
        service.add("XPML11")


def test_remove_and_history_count(service):
    service.add("MXRF11")
    assert service.history_count("MXRF11") == 1
    assert service.remove("MXRF11") is True
    assert service.history_count("MXRF11") == 1
