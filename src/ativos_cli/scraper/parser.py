"""Interpretação das páginas do fiis.com.br.

O fiis.com.br é usado só para o que as fontes oficiais não dão de forma simples:
- o nome e o CNPJ de cada fundo, a partir do objeto `dataLayer_content` da página do
  fundo (`pagePostTerms.meta`), para achar os avisos dele no FundosNet;
- o catálogo da pesquisa, do índice `data-island="search"` presente em todas as páginas.
"""

import html
import json
import re
from decimal import Decimal
from typing import Any

from ativos_cli.errors import ParseError
from ativos_cli.models import CatalogEntry, FundIdentity

_DATALAYER_MARKER = "var dataLayer_content ="
_SEARCH_ISLAND = re.compile(r'data-island="search"\s+data-props="([^"]*)"')
_TICKER = re.compile(r"^[A-Z]{4}\d{2}B?$")


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


def parse_fund_identity(page: str, expected_ticker: str | None = None) -> FundIdentity:
    meta = extract_meta(page)
    ticker = normalize_ticker(str(meta["ticker"]))
    if expected_ticker and ticker != normalize_ticker(expected_ticker):
        raise ParseError(f"A página retornou outro ativo ({ticker}).")
    cnpj = re.sub(r"\D", "", str(meta.get("cnpj") or ""))
    if len(cnpj) != 14:
        raise ParseError(f"CNPJ de {ticker} não encontrado no fiis.com.br.")
    name = _clean_name(meta.get("nome_pregao") or meta.get("fundname") or meta.get("name"))
    return FundIdentity(ticker=ticker, name=name, cnpj=cnpj)


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
