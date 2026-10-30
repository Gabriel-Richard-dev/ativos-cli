"""Acesso aos dados locais: carteira, snapshots e catálogo."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

from ativos_cli.errors import DatabaseError
from ativos_cli.models import CatalogEntry, FetchResult, FetchStatus, Snapshot
from ativos_cli.utils.dates import now_utc, parse_date


def _iso(value: object) -> str | None:
    return value.isoformat() if value is not None else None


def _dec(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


class AssetRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.conn:
                yield self.conn
        except sqlite3.Error as exc:
            raise DatabaseError(f"Falha no banco local: {exc}") from exc

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        try:
            return self.conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Falha no banco local: {exc}") from exc

    # --- ativos e carteira -------------------------------------------------

    def _ensure_asset(self, conn: sqlite3.Connection, ticker: str, name: str | None) -> int:
        conn.execute(
            "INSERT INTO assets (ticker, name, created_at) VALUES (?, ?, ?)"
            " ON CONFLICT(ticker) DO UPDATE SET name = COALESCE(excluded.name, assets.name)",
            (ticker, name, now_utc().isoformat()),
        )
        return conn.execute("SELECT id FROM assets WHERE ticker = ?", (ticker,)).fetchone()[0]

    def get_name(self, ticker: str) -> str | None:
        rows = self._query("SELECT name FROM assets WHERE ticker = ?", (ticker,))
        if rows and rows[0]["name"]:
            return rows[0]["name"]
        entry = self.get_catalog_entry(ticker)
        return entry.name if entry else None

    def in_wallet(self, ticker: str) -> bool:
        rows = self._query("SELECT in_wallet FROM assets WHERE ticker = ?", (ticker,))
        return bool(rows and rows[0]["in_wallet"])

    def add_to_wallet(self, ticker: str, name: str | None = None) -> bool:
        """Adiciona à carteira. Retorna False se o ativo já estava nela."""
        if self.in_wallet(ticker):
            return False
        with self._tx() as conn:
            self._ensure_asset(conn, ticker, name)
            conn.execute(
                "UPDATE assets SET in_wallet = 1, added_at = ? WHERE ticker = ?",
                (now_utc().isoformat(), ticker),
            )
        return True

    def remove_from_wallet(self, ticker: str, purge: bool = False) -> bool:
        """Remove da carteira. Com `purge`, apaga também o histórico do ativo."""
        if not self.in_wallet(ticker) and not purge:
            return False
        with self._tx() as conn:
            if purge:
                cur = conn.execute("DELETE FROM assets WHERE ticker = ?", (ticker,))
            else:
                cur = conn.execute(
                    "UPDATE assets SET in_wallet = 0, added_at = NULL WHERE ticker = ?", (ticker,)
                )
        return cur.rowcount > 0

    def wallet_tickers(self) -> list[str]:
        rows = self._query("SELECT ticker FROM assets WHERE in_wallet = 1 ORDER BY added_at, id")
        return [r["ticker"] for r in rows]

    # --- snapshots ---------------------------------------------------------

    def save_snapshot(self, result: FetchResult) -> Snapshot:
        """Grava a coleta (sucesso ou falha). Falhas nunca sobrescrevem dados válidos."""
        data = result.data if result.status == FetchStatus.OK else None
        with self._tx() as conn:
            asset_id = self._ensure_asset(conn, result.ticker, data.name if data else None)
            cur = conn.execute(
                """INSERT INTO asset_snapshots
                   (asset_id, status, datacom, data_pagamento, rendimento, rendimento_pct,
                    cotacao_base, cotacao_provisoria, cotacao_atual, source_field, source_url,
                    fetched_at, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset_id,
                    result.status.value,
                    _iso(data.datacom) if data else None,
                    _iso(data.data_pagamento) if data else None,
                    _dec(data.rendimento) if data else None,
                    _dec(data.rendimento_pct) if data else None,
                    _dec(data.cotacao_base) if data else None,
                    int(data.cotacao_provisoria) if data else 0,
                    _dec(data.cotacao_atual) if data else None,
                    data.source_field if data else None,
                    result.source_url,
                    result.fetched_at.isoformat(),
                    result.error,
                ),
            )
            snapshot_id = cur.lastrowid
        return self._snapshots("s.id = ?", (snapshot_id,))[0]

    def last_valid(self, ticker: str) -> Snapshot | None:
        rows = self._snapshots("a.ticker = ? AND s.status = 'ok'", (ticker,), limit=1)
        return rows[0] if rows else None

    def last_attempt(self, ticker: str) -> Snapshot | None:
        rows = self._snapshots("a.ticker = ?", (ticker,), limit=1)
        return rows[0] if rows else None

    def history(self, ticker: str, limit: int = 50) -> list[Snapshot]:
        return self._snapshots("a.ticker = ?", (ticker,), limit=limit)

    def count_snapshots(self, ticker: str) -> int:
        rows = self._query(
            "SELECT COUNT(*) FROM asset_snapshots s JOIN assets a ON a.id = s.asset_id"
            " WHERE a.ticker = ?",
            (ticker,),
        )
        return rows[0][0]

    def _snapshots(self, where: str, params: tuple, limit: int | None = None) -> list[Snapshot]:
        sql = (
            "SELECT s.*, a.ticker FROM asset_snapshots s JOIN assets a ON a.id = s.asset_id"
            f" WHERE {where} ORDER BY s.fetched_at DESC, s.id DESC"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._to_snapshot(r) for r in self._query(sql, params)]

    @staticmethod
    def _to_snapshot(row: sqlite3.Row) -> Snapshot:
        def dec(key: str) -> Decimal | None:
            return Decimal(row[key]) if row[key] is not None else None

        return Snapshot(
            id=row["id"],
            ticker=row["ticker"],
            status=FetchStatus(row["status"]),
            source_url=row["source_url"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            datacom=parse_date(row["datacom"]),
            data_pagamento=parse_date(row["data_pagamento"]),
            rendimento=dec("rendimento"),
            rendimento_pct=dec("rendimento_pct"),
            cotacao_base=dec("cotacao_base"),
            cotacao_provisoria=bool(row["cotacao_provisoria"]),
            cotacao_atual=dec("cotacao_atual"),
            source_field=row["source_field"],
            error=row["error"],
        )

    # --- catálogo ----------------------------------------------------------

    def replace_catalog(self, entries: list[CatalogEntry]) -> None:
        """Atualiza o catálogo, preservando a marca de validação dos ativos conhecidos."""
        now = now_utc().isoformat()
        with self._tx() as conn:
            conn.executemany(
                "INSERT INTO catalog (ticker, name, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(ticker) DO UPDATE SET name = excluded.name,"
                " updated_at = excluded.updated_at",
                [(e.ticker, e.name, now) for e in entries],
            )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('catalog_updated_at', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (now,),
            )

    def mark_validated(self, ticker: str, name: str | None) -> None:
        """Registra que a página do ativo foi consultada com sucesso."""
        now = now_utc().isoformat()
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO catalog (ticker, name, updated_at, validated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(ticker) DO UPDATE SET validated_at = excluded.validated_at",
                (ticker, name or ticker, now, now),
            )

    def list_catalog(self) -> list[CatalogEntry]:
        rows = self._query("SELECT ticker, name, validated_at FROM catalog ORDER BY ticker")
        return [self._to_entry(r) for r in rows]

    def get_catalog_entry(self, ticker: str) -> CatalogEntry | None:
        rows = self._query(
            "SELECT ticker, name, validated_at FROM catalog WHERE ticker = ?", (ticker,)
        )
        return self._to_entry(rows[0]) if rows else None

    def catalog_updated_at(self) -> datetime | None:
        rows = self._query("SELECT value FROM meta WHERE key = 'catalog_updated_at'")
        return datetime.fromisoformat(rows[0]["value"]) if rows else None

    @staticmethod
    def _to_entry(row: sqlite3.Row) -> CatalogEntry:
        validated = row["validated_at"]
        return CatalogEntry(
            ticker=row["ticker"],
            name=row["name"],
            validated_at=datetime.fromisoformat(validated) if validated else None,
        )
