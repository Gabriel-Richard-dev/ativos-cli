"""Cards de rendimento do Status Invest ("Último rendimento" e "Próximo rendimento").

A cotação-base e o Rend. % de cada rendimento saem destes cards, para os números
baterem com o que o site mostra. O site fica atrás do Cloudflare, que barra
requisições simples (HTTP 403), então a página é aberta num Chrome sem janela.
"""

import logging
import re
import threading
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import unescape

from ativos_cli.errors import FetchError
from ativos_cli.utils.dates import parse_date
from ativos_cli.utils.money import to_decimal

log = logging.getLogger(__name__)

BASE_URL = "https://statusinvest.com.br/fundos-imobiliarios"
PAGE_TIMEOUT_SECONDS = 30

CARD_TITLES = ("Último rendimento", "Próximo rendimento")
_FIELD = re.compile(
    r"<small[^>]*sub-title[^>]*>\s*([^<]+?)\s*</small>.*?<b[^>]*sub-value[^>]*>\s*([^<]*?)\s*</b>",
    re.S,
)
_VALUE = re.compile(r'<strong[^>]*class="value[^"]*"[^>]*>\s*([^<]*?)\s*</strong>', re.S)


@dataclass
class Card:
    rendimento: Decimal | None
    rendimento_pct: Decimal | None
    cotacao_base: Decimal | None
    datacom: date | None
    data_pagamento: date | None


def page_url(ticker: str) -> str:
    return f"{BASE_URL}/{ticker.lower()}"


def parse_cards(page: str) -> list[Card]:
    """Cards de rendimento da página do FII (sem valor provisionado, o card não vem)."""
    lower = page.lower()
    starts = sorted(i for t in CARD_TITLES if (i := lower.find(f">{t.lower()}</span>")) >= 0)
    # Cada card vai do seu título até o título do próximo ou o histórico de proventos.
    if not starts:
        return []
    ends = [*starts[1:], lower.find('id="earning-section"', starts[-1])]
    cards = []
    for start, end in zip(starts, ends, strict=True):
        block = page[start : end if end > start else start + 4000]
        fields = {unescape(k).strip().lower(): unescape(v) for k, v in _FIELD.findall(block)}
        value = _VALUE.search(block)
        cards.append(
            Card(
                rendimento=to_decimal(value.group(1)) if value else None,
                rendimento_pct=to_decimal(fields.get("rendimento")),
                cotacao_base=to_decimal(fields.get("cotação base")),
                datacom=parse_date(fields.get("data base")),
                data_pagamento=parse_date(fields.get("data pagamento")),
            )
        )
    return cards


class Browser:
    """Chrome sem janela, aberto na primeira página pedida e reaproveitado.

    O Selenium não é seguro entre threads: uma página por vez. Se o Chrome não abrir
    (não instalado, por exemplo), as próximas chamadas falham na hora, sem tentar de novo.
    """

    def __init__(self) -> None:
        self._driver = None
        self._broken = False
        self._lock = threading.Lock()

    def get(self, url: str) -> str:
        with self._lock:
            if self._broken:
                raise FetchError("Chrome indisponível para abrir o Status Invest.")
            try:
                driver = self._driver or self._start()
                driver.get(url)
                self._wait_cards(driver)
                return driver.page_source
            except FetchError:
                raise
            except Exception as exc:
                log.debug("Falha ao abrir %s no Chrome", url, exc_info=True)
                raise FetchError(f"Não foi possível abrir o Status Invest: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            if self._driver is not None:
                self._driver.quit()
                self._driver = None

    def _start(self):
        try:
            from selenium import webdriver

            options = webdriver.ChromeOptions()
            for arg in (
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
            ):
                options.add_argument(arg)
            # O user-agent padrão do modo headless ("HeadlessChrome") é barrado.
            options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
            )
            self._driver = webdriver.Chrome(options=options)
            self._driver.set_page_load_timeout(PAGE_TIMEOUT_SECONDS)
        except Exception as exc:
            self._broken = True
            log.debug("Chrome não abriu", exc_info=True)
            raise FetchError(f"Chrome indisponível para abrir o Status Invest: {exc}") from exc
        return self._driver

    @staticmethod
    def _wait_cards(driver) -> None:
        """Espera passar a checagem do Cloudflare e a página do fundo carregar."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            WebDriverWait(driver, PAGE_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.ID, "earning-section"))
            )
        except Exception as exc:
            if "não encontrada" in driver.title.lower() or "404" in driver.title:
                raise FetchError("Fundo não encontrado no Status Invest.") from exc
            raise FetchError("A página do Status Invest não carregou.") from exc
