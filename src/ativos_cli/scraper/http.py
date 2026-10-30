"""Cliente HTTP simples (urllib) com novas tentativas e intervalo mínimo por site.

Várias threads podem usar o mesmo cliente: cada site recebe no máximo uma requisição
a cada `config.DOWNLOAD_DELAY_SECONDS` (ou o valor de `config.HOST_DELAY_SECONDS`), e o
paralelismo é limitado por quem chama.
"""

import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ativos_cli import config
from ativos_cli.errors import FetchError

# Códigos em que vale tentar de novo; os demais viram erro na hora.
RETRY_STATUS = {408, 429, 500, 502, 503, 504, 522, 524}


class HttpStatusError(FetchError):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(describe_http_status(status))
        self.status = status
        self.url = url


def describe_http_status(status: int) -> str:
    if status == 404:
        return "Não encontrado (HTTP 404)."
    if status == 429:
        return "Limite de requisições atingido (HTTP 429). Tente novamente mais tarde."
    if status == 403:
        return "Acesso negado pelo site (HTTP 403)."
    if status >= 500:
        return f"O site está com problemas (HTTP {status})."
    return f"Resposta inesperada do site (HTTP {status})."


class Http:
    def __init__(
        self,
        delay: float = config.DOWNLOAD_DELAY_SECONDS,
        host_delays: dict[str, float] | None = None,
    ) -> None:
        self.delay = delay
        self.host_delays = config.HOST_DELAY_SECONDS if host_delays is None else host_delays
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}

    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        """Baixa a URL. Levanta HttpStatusError (status != 200) ou FetchError (rede)."""
        request = urllib.request.Request(
            url, headers={"User-Agent": config.USER_AGENT, **(headers or {})}
        )
        for attempt in range(config.RETRY_TIMES + 1):
            self._wait_turn(urlsplit(url).netloc)
            try:
                with urllib.request.urlopen(
                    request, timeout=config.DOWNLOAD_TIMEOUT_SECONDS
                ) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_STATUS or attempt == config.RETRY_TIMES:
                    raise HttpStatusError(exc.code, url) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == config.RETRY_TIMES:
                    raise FetchError(describe_network_error(exc)) from None
            time.sleep(2**attempt)
        raise AssertionError("inalcançável")

    def _wait_turn(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, now))
            self._next_slot[host] = slot + self.host_delays.get(host, self.delay)
        if slot > now:
            time.sleep(slot - now)


def describe_network_error(exc: Exception) -> str:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, TimeoutError) or "timed out" in str(reason):
        return "Tempo esgotado ao consultar o site."
    return "Falha de conexão. Verifique sua internet."
