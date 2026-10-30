"""Valores monetários sempre como Decimal."""

from decimal import ROUND_DOWN, Decimal, InvalidOperation

NA = "N/D"


def to_decimal(value: object) -> Decimal | None:
    """Converte números do JSON (já Decimal), strings "9.17" ou "1.234,56" em Decimal.

    Retorna None para valores ausentes, vazios ou não numéricos.
    Floats binários são rejeitados para não introduzir erro de precisão.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        text = value.strip().replace("R$", "").strip()
        if not text or text in {"-", "—", NA}:
            return None
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            result = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None
    return result if result.is_finite() else None


def format_brl(value: Decimal | None) -> str:
    """Formata como "R$ 1.234,56". Rendimentos com mais casas mantêm a precisão."""
    if value is None:
        return NA
    places = min(8, max(2, -value.normalize().as_tuple().exponent))
    text = f"{value:,.{places}f}"
    text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}"


def yield_percent(rendimento: Decimal | None, cotacao_base: Decimal | None) -> Decimal | None:
    """Rendimento em % da cotação-base (dividend yield do período)."""
    if rendimento is None or not cotacao_base:
        return None
    return rendimento / cotacao_base * 100


def truncate(value: Decimal | None, places: int) -> Decimal | None:
    """Corta (sem arredondar) em `places` casas decimais: 1,0909 -> 1,090."""
    if value is None:
        return None
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def format_percent(value: Decimal | None) -> str:
    """Formata como "1,090%"."""
    if value is None:
        return NA
    return f"{value:f}%".replace(".", ",")
