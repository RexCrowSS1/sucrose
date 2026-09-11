"""Persistent PostgreSQL configuration; local JSON remains available for desktop use."""
import asyncio
from copy import deepcopy
import logging

import psycopg
from psycopg.types.json import Jsonb

from .store import Store, defaults
from .utils import UserError

log = logging.getLogger("sucrose.storage")


class StorageError(UserError):
    pass


class PostgresStore(Store):
    def __init__(self, url):
        self.url = url
        self.data = {}
        self._write_lock = asyncio.Lock()

    async def connect(self):
        connection = await psycopg.AsyncConnection.connect(self.url, connect_timeout=10)
        try:
            await connection.execute("SET statement_timeout = 10000")
            await connection.execute("SET lock_timeout = 5000")
        except Exception:
            await connection.close()
            raise
        return connection

    async def initialize(self):
        try:
            async with await self.connect() as connection:
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS varah_guild_config (
                        guild_id TEXT PRIMARY KEY,
                        config JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                cursor = await connection.execute("SELECT guild_id, config FROM varah_guild_config")
                rows = await cursor.fetchall()
            self.data = {guild_id: config for guild_id, config in rows}
            if not all(isinstance(c, dict) for c in self.data.values()):
                raise StorageError("Format konfigurasi PostgreSQL tidak valid. Pulihkan backup.")
        except psycopg.Error as exc:
            log.error("Database initialization failed (%s)", type(exc).__name__)
            raise StorageError("PostgreSQL tidak dapat diakses. Periksa DATABASE_URL dan izin database.") from None

    def update(self, guild_id, change):
        raise RuntimeError("PostgresStore memerlukan await update_async().")

    async def update_async(self, guild_id, change):
        key = str(guild_id)
        async with self._write_lock:
            try:
                async with await self.connect() as connection:
                    await connection.execute(
                        "INSERT INTO varah_guild_config (guild_id, config) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (key, Jsonb(defaults())),
                    )
                    cursor = await connection.execute("SELECT config FROM varah_guild_config WHERE guild_id = %s FOR UPDATE", (key,))
                    row = await cursor.fetchone()
                    # Normalize legacy JSON without changing the live cache before commit.
                    snapshot = Store.__new__(Store)
                    snapshot.data = {key: row[0]}
                    config = snapshot.get(key)
                    change(config)
                    await connection.execute(
                        "UPDATE varah_guild_config SET config = %s, updated_at = now() WHERE guild_id = %s",
                        (Jsonb(config), key),
                    )
                self.data[key] = deepcopy(config)
                return deepcopy(config)
            except psycopg.Error as exc:
                log.error("Database write failed (%s)", type(exc).__name__)
                raise StorageError("Pengaturan gagal disimpan ke PostgreSQL. Coba lagi; bot tidak melaporkan penyimpanan berhasil.") from None

    async def import_missing(self, source):
        """Explicit, non-destructive migration: never overwrite existing guild rows."""
        count = 0
        try:
            async with await self.connect() as connection:
                for guild_id in source.data:
                    cursor = await connection.execute(
                        "INSERT INTO varah_guild_config (guild_id, config) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING guild_id",
                        (str(guild_id), Jsonb(source.get(guild_id))),
                    )
                    if await cursor.fetchone():
                        count += 1
            await self.initialize()
            return count
        except psycopg.Error as exc:
            log.error("Database import failed (%s)", type(exc).__name__)
            raise StorageError("Impor konfigurasi gagal. Periksa koneksi PostgreSQL.") from None
