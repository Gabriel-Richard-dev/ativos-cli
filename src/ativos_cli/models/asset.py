"""Modelos de domínio."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class FundData(BaseModel):
    """Campos extraídos da página de um FII."""

    ticker: str
    name: str | None = None
    datacom: date | None = None
    data_pagamento: date | None = None
    rendimento: Decimal | None = None
    # Rendimento em % da cotação-base, como o site informa (sem arredondar).
    rendimento_pct: Decimal | None = None
    cotacao_base: Decimal | None = None
    cotacao_atual: Decimal | None = None
    data_cotacao: date | None = None
    # Grupo de campos da fonte usado para o rendimento ("pr_*" ou "ur_*").
    source_field: str | None = None
    notes: list[str] = Field(default_factory=list)


class FetchStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    ERROR = "error"


class FetchResult(BaseModel):
    """Resultado de uma coleta. Em falha, `data` é None e `error` explica o motivo."""

    ticker: str
    status: FetchStatus
    source_url: str
    fetched_at: datetime
    data: FundData | None = None
    error: str | None = None


class CatalogEntry(BaseModel):
    ticker: str
    name: str
    validated_at: datetime | None = None


class Snapshot(BaseModel):
    """Uma coleta gravada no histórico (com sucesso ou falha)."""

    id: int
    ticker: str
    status: FetchStatus
    source_url: str
    fetched_at: datetime
    datacom: date | None = None
    data_pagamento: date | None = None
    rendimento: Decimal | None = None
    rendimento_pct: Decimal | None = None
    cotacao_base: Decimal | None = None
    cotacao_atual: Decimal | None = None
    source_field: str | None = None
    error: str | None = None


class DisplayStatus(StrEnum):
    UPDATED = "Atualizado"
    CACHED = "Em cache"
    FAILED = "Falha"
    NO_DATA = "Sem dados"


class AssetView(BaseModel):
    """O que a interface exibe para um ativo: último dado válido + estado da última coleta."""

    ticker: str
    name: str | None = None
    status: DisplayStatus
    valid: Snapshot | None = None
    last_attempt: Snapshot | None = None
    stale: bool = False
    in_wallet: bool = False

    @property
    def last_error(self) -> str | None:
        if self.last_attempt and self.last_attempt.status != FetchStatus.OK:
            return self.last_attempt.error
        return None
