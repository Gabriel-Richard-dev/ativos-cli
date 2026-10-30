"""Configuração: caminhos locais, fonte de dados e parâmetros de coleta."""

import os
from datetime import timedelta
from pathlib import Path

from platformdirs import user_data_dir

from ativos_cli import __version__

APP_NAME = "ativos-cli"

# Rendimentos: avisos oficiais no FundosNet; cotação-base do Status Invest (reserva:
# cotações da B3). O fiis.com.br dá o CNPJ
# de cada fundo (uma vez) e o catálogo da pesquisa. O nome aparece nos detalhes.
SOURCE_NAME = "B3 (FundosNet) e Status Invest"
BASE_URL = "https://fiis.com.br"
CATALOG_URL = f"{BASE_URL}/lista-de-fundos-imobiliarios/"
USER_AGENT = f"ativos-cli/{__version__} (uso pessoal)"

# Limites de acesso: até PARALLEL_REQUESTS ativos consultados ao mesmo tempo e um
# intervalo mínimo entre requisições ao mesmo site.
PARALLEL_REQUESTS = 4
DOWNLOAD_DELAY_SECONDS = 0.25
# Os servidores públicos da B3 (FundosNet e cotações) aguentam um ritmo maior.
HOST_DELAY_SECONDS = {
    "fnet.bmfbovespa.com.br": 0.1,
    "bvmf.bmfbovespa.com.br": 0.1,
    "cotacao.b3.com.br": 0.1,
    "sistemaswebb3-listados.b3.com.br": 0.1,
}
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
