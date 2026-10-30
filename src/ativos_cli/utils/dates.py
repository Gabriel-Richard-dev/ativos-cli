"""Datas: ISO (YYYY-MM-DD) para armazenamento, DD/MM/AAAA para exibição."""

import re
from datetime import UTC, date, datetime

NA = "N/D"

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_BR_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def parse_date(value: object) -> date | None:
    """Aceita "2026-09-30", "2026-09-30T00:00:00" ou "30/09/2026"."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if m := _ISO_DATE.match(text):
            year, month, day = (int(g) for g in m.groups())
        elif m := _BR_DATE.match(text):
            day, month, year = (int(g) for g in m.groups())
        else:
            return None
        parsed = date(year, month, day)
    except ValueError:
        return None
    # O site usa datas "zeradas" (0001-01-01) para indicar ausência.
    return parsed if parsed.year >= 1990 else None


def format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else NA


def now_utc() -> datetime:
    return datetime.now(UTC)


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return NA
    return value.astimezone().strftime("%d/%m/%Y %H:%M")
