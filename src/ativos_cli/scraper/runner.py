"""Ciclo de vida do Scrapy.

O reactor do Twisted não pode ser reiniciado dentro do mesmo processo, e a carteira
interativa atualiza os dados várias vezes. Por isso cada coleta roda em um subprocesso
(`python -m ativos_cli.scraper.runner ...`), que devolve os itens como JSON Lines.
No executável gerado pelo PyInstaller não há `python`: o próprio executável é chamado
com `RUNNER_FLAG` (ver `main.run`).
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable

from ativos_cli import config
from ativos_cli.errors import FetchError
from ativos_cli.models import CatalogEntry, FetchResult, FetchStatus
from ativos_cli.utils.dates import now_utc

log = logging.getLogger(__name__)

ResultCallback = Callable[[FetchResult], None]

RUNNER_FLAG = "--scraper-runner"


def collector_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, RUNNER_FLAG]
    return [sys.executable, "-m", "ativos_cli.scraper.runner"]


def scrapy_settings(debug: bool = False) -> dict:
    return {
        "USER_AGENT": config.USER_AGENT,
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": config.DOWNLOAD_DELAY_SECONDS,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": config.DOWNLOAD_DELAY_SECONDS,
        "DOWNLOAD_TIMEOUT": config.DOWNLOAD_TIMEOUT_SECONDS,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": config.RETRY_TIMES,
        "RETRY_HTTP_CODES": [408, 429, 500, 502, 503, 504, 522, 524],
        "HTTPERROR_ALLOW_ALL": True,
        "COOKIES_ENABLED": False,
        "TELNETCONSOLE_ENABLED": False,
        # Esse aviso lê o código-fonte dos spiders, que não existe no executável.
        "WARN_ON_GENERATOR_RETURN_VALUE": False,
        "LOG_ENABLED": debug,
        "LOG_LEVEL": "DEBUG" if debug else "ERROR",
        "ITEM_PIPELINES": {"ativos_cli.scraper.pipelines.JsonLinesStdoutPipeline": 100},
    }


class ScrapyFetcher:
    """Executa os spiders em subprocesso e converte a saída em modelos."""

    def __init__(self, debug: bool = False) -> None:
        self.debug = debug

    def fetch(
        self, tickers: list[str], on_result: ResultCallback | None = None
    ) -> list[FetchResult]:
        if not tickers:
            return []
        results: dict[str, FetchResult] = {}
        timeout = 30 + len(tickers) * (
            config.DOWNLOAD_DELAY_SECONDS
            + config.DOWNLOAD_TIMEOUT_SECONDS * (config.RETRY_TIMES + 1)
        )
        try:
            for item in self._run(["fund", *tickers], timeout):
                if item.get("kind") != "fund":
                    continue
                result = FetchResult.model_validate({k: v for k, v in item.items() if k != "kind"})
                results[result.ticker] = result
                if on_result:
                    on_result(result)
        except FetchError as exc:
            error = str(exc)
        else:
            error = "O coletor terminou sem retornar dados para este ativo."

        # Garante um resultado por ticker, mesmo se o subprocesso falhar no meio.
        for ticker in tickers:
            if ticker not in results:
                result = FetchResult(
                    ticker=ticker,
                    status=FetchStatus.ERROR,
                    source_url=config.fund_url(ticker),
                    fetched_at=now_utc(),
                    error=error,
                )
                results[ticker] = result
                if on_result:
                    on_result(result)
        return [results[t] for t in tickers]

    def fetch_catalog(self) -> list[CatalogEntry]:
        for item in self._run(["catalog"], timeout=120):
            if item.get("kind") != "catalog":
                continue
            if item.get("error"):
                raise FetchError(item["error"])
            return [CatalogEntry.model_validate(e) for e in item["entries"]]
        raise FetchError("O coletor não retornou o catálogo.")

    def _run(self, args: list[str], timeout: float):
        cmd = [*collector_command(), *args]
        if self.debug:
            cmd.append("--debug")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        log.debug("Executando coletor: %s", cmd)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=None if self.debug else subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
            )
        except OSError as exc:
            raise FetchError(f"Não foi possível iniciar o coletor: {exc}") from exc

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    log.debug("Linha inesperada do coletor: %r", line)
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise FetchError("Tempo esgotado na coleta.") from exc
        finally:
            if proc.poll() is None:
                proc.kill()

        if proc.returncode != 0:
            raise FetchError(f"O coletor falhou (código {proc.returncode}).")


def main(argv: list[str] | None = None) -> int:
    from scrapy.crawler import CrawlerProcess

    from ativos_cli.scraper.spiders.fiis import CatalogSpider, FundSpider

    parser = argparse.ArgumentParser(prog="ativos_cli.scraper.runner")
    parser.add_argument("kind", choices=["fund", "catalog"])
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    process = CrawlerProcess(settings=scrapy_settings(args.debug), install_root_handler=args.debug)
    if args.kind == "fund":
        process.crawl(FundSpider, tickers=args.tickers)
    else:
        process.crawl(CatalogSpider)
    process.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
