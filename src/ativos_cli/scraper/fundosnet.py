"""Avisos de rendimentos no FundosNet (B3), a fonte oficial dos FIIs.

Cada fundo publica um "Aviso aos Cotistas - Estruturado" do tipo "Rendimentos e
Amortizações" com data-com, valor por cota e data de pagamento, em XML.
"""

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ativos_cli.errors import ParseError
from ativos_cli.utils.dates import parse_date
from ativos_cli.utils.money import to_decimal

BASE_URL = "https://fnet.bmfbovespa.com.br/fnet/publico"
# Categoria "Aviso aos Cotistas - Estruturado", tipo "Rendimentos e Amortizações".
CATEGORY_ID = 14
TYPE_ID = 41
# Avisos mais recentes listados por fundo. Só são baixados até achar o do ticker
# (fundos com mais de uma classe publicam um aviso por classe).
NOTICES_TO_CHECK = 3


@dataclass
class Notice:
    id: int
    delivered_at: str


@dataclass
class Dividend:
    datacom: date
    valor: Decimal
    data_pagamento: date | None
    notice_id: int

    def to_dict(self) -> dict:
        return {
            "datacom": self.datacom.isoformat(),
            "valor": str(self.valor),
            "data_pagamento": self.data_pagamento.isoformat() if self.data_pagamento else None,
            "notice_id": self.notice_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Dividend":
        return cls(
            datacom=date.fromisoformat(data["datacom"]),
            valor=Decimal(data["valor"]),
            data_pagamento=parse_date(data["data_pagamento"]),
            notice_id=int(data["notice_id"]),
        )


def search_url(cnpj: str, limit: int = NOTICES_TO_CHECK) -> str:
    return (
        f"{BASE_URL}/pesquisarGerenciadorDocumentosDados?d=1&s=0&l={limit}"
        "&o%5B0%5D%5BdataEntrega%5D=desc&tipoFundo=1"
        f"&idCategoriaDocumento={CATEGORY_ID}&idTipoDocumento={TYPE_ID}"
        f"&idEspecieDocumento=0&cnpjFundo={cnpj}"
    )


def document_url(notice_id: int) -> str:
    return f"{BASE_URL}/downloadDocumento?id={notice_id}"


def notice_page_url(notice_id: int) -> str:
    return f"{BASE_URL}/exibirDocumento?id={notice_id}"


def search_page_url(cnpj: str) -> str:
    return f"{BASE_URL}/abrirGerenciadorDocumentosCVM?cnpjFundo={cnpj}"


def parse_search(payload: bytes) -> list[Notice]:
    try:
        rows = json.loads(payload)["data"]
        return [Notice(id=int(r["id"]), delivered_at=r.get("dataEntrega") or "") for r in rows]
    except (ValueError, KeyError, TypeError) as exc:
        raise ParseError("Resposta inesperada da busca do FundosNet.") from exc


def parse_notice(payload: bytes, ticker: str, notice_id: int) -> Dividend | None:
    """Rendimento do `ticker` no aviso, ou None se o aviso não tiver um para ele."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ParseError("Aviso do FundosNet em formato inesperado.") from exc
    for provento in root.iter("Provento"):
        if (provento.findtext("CodNegociacao") or "").strip().upper() != ticker:
            continue
        rendimento = provento.find("Rendimento")
        if rendimento is None:
            continue
        datacom = parse_date(rendimento.findtext("DataBase"))
        valor = to_decimal(rendimento.findtext("ValorProvento"))
        if datacom is None or valor is None:
            continue
        return Dividend(
            datacom=datacom,
            valor=valor,
            data_pagamento=parse_date(rendimento.findtext("DataPagamento")),
            notice_id=notice_id,
        )
    return None
