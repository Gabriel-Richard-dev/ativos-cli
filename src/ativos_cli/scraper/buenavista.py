"""Agenda de rendimentos dos ETFs da Buena Vista Capital (ex.: QQQI11, COIN11).

A gestora divulga no site a data-com, a data ex e o pagamento dos próximos meses antes
de o valor ser declarado (o valor sai no dia da data-com, junto com o provento na B3).
A página do fundo lê esses dados de um serviço JSON do próprio site, usado aqui.
Linhas sem "Dividendo por Cota" são datas previstas, ainda sem valor.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ativos_cli.errors import ParseError
from ativos_cli.utils.dates import parse_date
from ativos_cli.utils.money import to_decimal

BASE_URL = "https://www.buenavista.capital/wp-json/v1/supabase_api/dividends-cdi-report"
# Os ETFs da gestora são reconhecidos pelo nome na lista de ETFs da B3.
NAME_MARK = "BUENA VISTA"


@dataclass(frozen=True)
class Scheduled:
    datacom: date
    data_pagamento: date | None
    valor: Decimal | None  # None: data prevista, valor ainda não declarado


def manages(name: str | None) -> bool:
    return NAME_MARK in (name or "").upper()


def schedule_url(ticker: str) -> str:
    return f"{BASE_URL}/{ticker}"


def parse_schedule(payload: bytes, ticker: str) -> list[Scheduled]:
    """Rendimentos (declarados e previstos) do ticker, da data-com mais antiga à mais nova."""
    try:
        rows = json.loads(payload)["Dividends x CDI"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ParseError("Resposta inesperada da agenda da Buena Vista.") from exc
    out = {}
    for row in rows:
        if not isinstance(row, dict) or (row.get("Ticker") or "").upper() != ticker:
            continue
        datacom = parse_date(row.get("Data COM"))
        if datacom is None:
            continue
        valor = to_decimal(row.get("Dividendo por Cota"))
        out[datacom] = Scheduled(
            datacom=datacom,
            data_pagamento=parse_date(row.get("Data Liquidação")),
            valor=valor if valor else None,
        )
    return sorted(out.values(), key=lambda s: s.datacom)
