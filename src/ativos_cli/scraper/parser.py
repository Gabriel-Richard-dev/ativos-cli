"""Interpretação das páginas do fiis.com.br.

A página de cada fundo embute um objeto JavaScript `dataLayer_content` cujo caminho
`pagePostTerms.meta` traz os dados do fundo. Campos usados:

- `ur_data_base` / `ur_valor` / `ur_cotacao_base` / `ur_data_pagamento`: último rendimento.
- `pr_database` / `pr_valor` / `pr_cotacaobase` / `pr_datapagamento`: próximo rendimento.
- `valor` / `datacotacao`: cotação atual (exibida apenas nos detalhes, nunca como cotação-base).

A data-com é a "data com" do rendimento. A cotação-base é o preço de referência que o site
associa ao rendimento (usado no cálculo do yield), distinto da cotação atual.

O catálogo de fundos vem do índice de busca `data-island="search"`, presente no cabeçalho
de todas as páginas.
"""

import html
import json
import re
from decimal import Decimal
from typing import Any

from ativos_cli.errors import ParseError
from ativos_cli.models import CatalogEntry, FundData
from ativos_cli.utils.dates import parse_date
from ativos_cli.utils.money import to_decimal, truncate

_DATALAYER_MARKER = "var dataLayer_content ="
YIELD_PLACES = 3
_SEARCH_ISLAND = re.compile(r'data-island="search"\s+data-props="([^"]*)"')
_TICKER = re.compile(r"^[A-Z]{4}\d{2}B?$")

# (rótulo, campo da data-com, campo do valor, campo da cotação-base, campo do pagamento,
#  campo do rendimento em %)
_DIVIDEND_GROUPS = (
    ("pr_*", "pr_database", "pr_valor", "pr_cotacaobase", "pr_datapagamento", "pr_rendimento"),
    (
        "ur_*",
        "ur_data_base",
        "ur_valor",
        "ur_cotacao_base",
        "ur_data_pagamento",
        "ur_rendimento",
    ),
)


def normalize_ticker(value: str) -> str:
    return value.strip().upper()


def is_valid_ticker(value: str) -> bool:
    return bool(_TICKER.match(value))


def extract_meta(page: str) -> dict[str, Any]:
    """Retorna `pagePostTerms.meta` do dataLayer. Números chegam como Decimal."""
    start = page.find(_DATALAYER_MARKER)
    if start < 0:
        raise ParseError("Estrutura da página mudou: dataLayer_content não encontrado.")
    brace = page.find("{", start)
    try:
        obj, _ = json.JSONDecoder(parse_float=Decimal).raw_decode(page, brace)
    except (ValueError, IndexError) as exc:
        raise ParseError("Estrutura da página mudou: dataLayer_content inválido.") from exc
    meta = (obj.get("pagePostTerms") or {}).get("meta") if isinstance(obj, dict) else None
    if not isinstance(meta, dict) or not meta.get("ticker"):
        raise ParseError("Estrutura da página mudou: dados do fundo ausentes.")
    return meta


def parse_fund_page(page: str, expected_ticker: str | None = None) -> FundData:
    meta = extract_meta(page)
    ticker = normalize_ticker(str(meta["ticker"]))
    if expected_ticker and ticker != normalize_ticker(expected_ticker):
        raise ParseError(f"A página retornou outro ativo ({ticker}).")

    data = FundData(
        ticker=ticker,
        name=_clean_name(meta.get("nome_pregao") or meta.get("fundname") or meta.get("name")),
        cotacao_atual=to_decimal(meta.get("valor")),
        data_cotacao=parse_date(meta.get("datacotacao")),
    )

    candidates = []
    for label, f_date, f_value, f_base, f_pay, f_pct in _DIVIDEND_GROUPS:
        datacom = parse_date(meta.get(f_date))
        rendimento = to_decimal(meta.get(f_value))
        if datacom is None and rendimento is None:
            continue
        if datacom is None or rendimento is None:
            # Sem o par data-com + valor não há como associar o rendimento com segurança.
            data.notes.append(f"Campos {label} incompletos; ignorados por ambiguidade.")
            continue
        candidates.append(
            (datacom, label, rendimento, meta.get(f_base), meta.get(f_pay), meta.get(f_pct))
        )

    if candidates:
        # O grupo com a data-com mais recente vence; em empate, "pr_*" (listado primeiro).
        datacom, label, rendimento, base, pay, pct = max(candidates, key=lambda c: c[0])
        data.datacom = datacom
        data.rendimento = rendimento
        data.cotacao_base = to_decimal(base)
        # O site manda até 14 casas; guardamos só 3, cortadas (sem arredondar).
        data.rendimento_pct = truncate(to_decimal(pct), YIELD_PLACES)
        data.data_pagamento = parse_date(pay)
        data.source_field = label
    return data


def parse_catalog(page: str) -> list[CatalogEntry]:
    match = _SEARCH_ISLAND.search(page)
    if not match:
        raise ParseError("Estrutura da página mudou: índice de busca não encontrado.")
    try:
        props = json.loads(html.unescape(match.group(1)))
        index = props["index"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ParseError("Estrutura da página mudou: índice de busca inválido.") from exc

    entries: dict[str, CatalogEntry] = {}
    for item in index:
        if not isinstance(item, dict):
            continue
        ticker = normalize_ticker(str(item.get("tk") or ""))
        if not is_valid_ticker(ticker):
            continue
        entries[ticker] = CatalogEntry(ticker=ticker, name=_clean_name(item.get("nm")) or ticker)
    if not entries:
        raise ParseError("Índice de busca vazio.")
    return sorted(entries.values(), key=lambda e: e.ticker)


def _clean_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(html.unescape(value).split())
    return text or None
