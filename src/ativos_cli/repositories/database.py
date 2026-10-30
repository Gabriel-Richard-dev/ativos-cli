"""Conexão SQLite e migrações de esquema (controladas por PRAGMA user_version)."""

import sqlite3
from pathlib import Path

from ativos_cli.errors import DatabaseError

# `assets` guarda todo ativo já consultado; `in_wallet` indica se ele está na carteira.
# Assim remover da carteira não apaga o histórico de snapshots.
MIGRATIONS = [
    """
    CREATE TABLE assets (
        id          INTEGER PRIMARY KEY,
        ticker      TEXT NOT NULL UNIQUE,
        name        TEXT,
        asset_type  TEXT NOT NULL DEFAULT 'FII',
        created_at  TEXT NOT NULL,
        in_wallet   INTEGER NOT NULL DEFAULT 0,
        added_at    TEXT
    );

    CREATE TABLE asset_snapshots (
        id              INTEGER PRIMARY KEY,
        asset_id        INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
        status          TEXT NOT NULL,
        datacom         TEXT,
        data_pagamento  TEXT,
        rendimento      TEXT,
        cotacao_base    TEXT,
        cotacao_atual   TEXT,
        source_field    TEXT,
        source_url      TEXT NOT NULL,
        fetched_at      TEXT NOT NULL,
        error           TEXT
    );
    CREATE INDEX idx_snapshots_asset ON asset_snapshots(asset_id, fetched_at);

    CREATE TABLE catalog (
        ticker        TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        validated_at  TEXT
    );

    CREATE TABLE meta (
        key    TEXT PRIMARY KEY,
        value  TEXT
    );
    """,
    # Consultas gravadas antes desta versão ficam sem o percentual do site.
    "ALTER TABLE asset_snapshots ADD COLUMN rendimento_pct TEXT;",
    "ALTER TABLE asset_snapshots ADD COLUMN cotacao_provisoria INTEGER NOT NULL DEFAULT 0;",
]


def connect(path: Path) -> sqlite3.Connection:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # A interface em tela cheia usa o banco a partir de uma thread de trabalho
        # (uma operação por vez), por isso a conexão não fica presa à thread que a criou.
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        migrate(conn)
    except (sqlite3.Error, OSError) as exc:
        raise DatabaseError(f"Não foi possível abrir o banco local em {path}: {exc}") from exc
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        with conn:
            conn.executescript(f"BEGIN; {script} PRAGMA user_version = {number}; COMMIT;")
