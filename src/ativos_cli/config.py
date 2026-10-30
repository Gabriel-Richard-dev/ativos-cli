"""Configuração: caminhos locais, fonte de dados e parâmetros de coleta."""

import os
from datetime import timedelta
from pathlib import Path

from platformdirs import user_data_dir

from ativos_cli import __version__

APP_NAME = "ativos-cli"

SOURCE_NAME = "fiis.com.br"
BASE_URL = "https://fiis.com.br"
CATALOG_URL = f"{BASE_URL}/lista-de-fundos-imobiliarios/"
USER_AGENT = f"ativos-cli/{__version__} (uso pessoal)"

# Limites de acesso ao site: uma requisição por vez, com intervalo entre elas.
DOWNLOAD_DELAY_SECONDS = 1.0
DOWNLOAD_TIMEOUT_SECONDS = 20
RETRY_TIMES = 2

# A pesquisa consulta a página de cada resultado para mostrar a data-com.
SEARCH_LIMIT = 10
# Na pesquisa, ativos consultados há menos tempo que isso usam o dado salvo.
SEARCH_FRESH_FOR = timedelta(hours=1)

# Dados coletados há mais tempo que isso são marcados como potencialmente desatualizados.
STALE_AFTER = timedelta(hours=24)
CATALOG_STALE_AFTER = timedelta(days=30)


def fund_url(ticker: str) -> str:
    return f"{BASE_URL}/{ticker.lower()}/"


def data_dir() -> Path:
    """Diretório de dados do usuário (sobrescrevível por ATIVOS_DATA_DIR)."""
    override = os.environ.get("ATIVOS_DATA_DIR")
    path = Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "ativos.db"
