"""Exceções da aplicação. Mensagens curtas, voltadas ao usuário."""


class AtivosError(Exception):
    """Erro esperado, exibido ao usuário sem traceback."""


class InvalidTickerError(AtivosError):
    def __init__(self, ticker: str) -> None:
        super().__init__(f"Ticker inválido: {ticker!r}. Use o formato ABCD11.")
        self.ticker = ticker


class AssetNotFoundError(AtivosError):
    def __init__(self, ticker: str) -> None:
        super().__init__(f"Ativo {ticker} não encontrado.")
        self.ticker = ticker


class FetchError(AtivosError):
    """Falha de rede, timeout, HTTP inesperado ou limitação de requisições."""


class ParseError(AtivosError):
    """A página não tem a estrutura esperada (provável mudança no site)."""


class DatabaseError(AtivosError):
    """Falha ao ler ou gravar o banco local."""
