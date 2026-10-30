"""Regras de negócio: consultas, atualização, carteira e uso do cache."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from ativos_cli import config
from ativos_cli.errors import AssetNotFoundError, FetchError, InvalidTickerError
from ativos_cli.models import AssetView, DisplayStatus, FetchResult, FetchStatus
from ativos_cli.repositories.asset_repository import AssetRepository
from ativos_cli.scraper.parser import is_valid_ticker, normalize_ticker
from ativos_cli.services import Fetcher
from ativos_cli.utils.dates import now_utc

ProgressCallback = Callable[[FetchResult], None]


@dataclass
class RefreshSummary:
    views: list[AssetView] = field(default_factory=list)

    @property
    def succeeded(self) -> list[AssetView]:
        return [v for v in self.views if v.status == DisplayStatus.UPDATED]

    @property
    def failed(self) -> list[AssetView]:
        return [v for v in self.views if v.status != DisplayStatus.UPDATED]


@dataclass
class AddOutcome:
    added: bool
    view: AssetView
    warning: str | None = None


def validate_ticker(raw: str) -> str:
    ticker = normalize_ticker(raw)
    if not is_valid_ticker(ticker):
        raise InvalidTickerError(raw)
    return ticker


class AssetService:
    def __init__(self, repo: AssetRepository, fetcher: Fetcher) -> None:
        self.repo = repo
        self.fetcher = fetcher

    def view(self, ticker: str, updated_now: bool = False) -> AssetView:
        """Monta a visão do ativo a partir do banco.

        Só uma coleta bem-sucedida feita nesta execução (`updated_now`) marca o ativo
        como "Atualizado". Dado apenas lido do banco é sempre "Em cache".
        """
        valid = self.repo.last_valid(ticker)
        attempt = self.repo.last_attempt(ticker)
        if updated_now and valid is not None:
            status = DisplayStatus.UPDATED
        elif valid is not None:
            status = DisplayStatus.CACHED
        elif attempt is not None:
            status = DisplayStatus.FAILED
        else:
            status = DisplayStatus.NO_DATA
        stale = valid is not None and now_utc() - valid.fetched_at > config.STALE_AFTER
        return AssetView(
            ticker=ticker,
            name=self.repo.get_name(ticker),
            status=status,
            valid=valid,
            last_attempt=attempt,
            stale=stale and status != DisplayStatus.UPDATED,
            in_wallet=self.repo.in_wallet(ticker),
        )

    def _record(self, result: FetchResult) -> AssetView:
        self.repo.save_snapshot(result)
        if result.status == FetchStatus.OK and result.data:
            self.repo.mark_validated(result.ticker, result.data.name)
        return self.view(result.ticker, updated_now=result.status == FetchStatus.OK)

    def lookup(self, raw_ticker: str) -> AssetView:
        """Consulta um ativo no site. Sem dados válidos anteriores, falhas viram exceção."""
        ticker = validate_ticker(raw_ticker)
        result = self.fetcher.fetch([ticker])[0]
        view = self._record(result)
        if view.valid is None:
            if result.status == FetchStatus.NOT_FOUND:
                raise AssetNotFoundError(ticker)
            if result.status == FetchStatus.ERROR:
                raise FetchError(result.error or "Falha na consulta.")
        return view

    def is_fresh(self, ticker: str, max_age: timedelta) -> bool:
        """Há dado válido coletado há menos de `max_age`."""
        valid = self.repo.last_valid(ticker)
        return valid is not None and now_utc() - valid.fetched_at < max_age

    def wallet_views(self) -> list[AssetView]:
        """Carteira a partir do cache, sem consultar o site."""
        return [self.view(t) for t in self.repo.wallet_tickers()]

    def refresh(
        self, tickers: list[str] | None = None, on_progress: ProgressCallback | None = None
    ) -> RefreshSummary:
        """Atualiza os ativos informados (ou a carteira toda). Falhas não interrompem os demais."""
        targets = [validate_ticker(t) for t in tickers] if tickers else self.repo.wallet_tickers()
        summary = RefreshSummary()

        def handle(result: FetchResult) -> None:
            summary.views.append(self._record(result))
            if on_progress:
                on_progress(result)

        self.fetcher.fetch(targets, on_result=handle)
        order = {t: i for i, t in enumerate(targets)}
        summary.views.sort(key=lambda v: order.get(v.ticker, len(order)))
        return summary

    def add(self, raw_ticker: str) -> AddOutcome:
        ticker = validate_ticker(raw_ticker)
        if self.repo.in_wallet(ticker):
            return AddOutcome(added=False, view=self.view(ticker))

        warning = None
        if self.repo.last_valid(ticker) is None:
            result = self.fetcher.fetch([ticker])[0]
            self._record(result)
            if result.status == FetchStatus.NOT_FOUND:
                raise AssetNotFoundError(ticker)
            if result.status == FetchStatus.ERROR:
                if self.repo.get_catalog_entry(ticker) is None:
                    raise FetchError(
                        f"Não foi possível validar {ticker}: {result.error or 'falha na consulta.'}"
                    )
                warning = f"{ticker} adicionado sem dados: {result.error}"

        self.repo.add_to_wallet(ticker, self.repo.get_name(ticker))
        return AddOutcome(added=True, view=self.view(ticker), warning=warning)

    def remove(self, raw_ticker: str, purge: bool = False) -> bool:
        return self.repo.remove_from_wallet(validate_ticker(raw_ticker), purge=purge)

    def history_count(self, raw_ticker: str) -> int:
        return self.repo.count_snapshots(validate_ticker(raw_ticker))
