from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as connection:
            await connection.execute("PRAGMA journal_mode=WAL;")
            await connection.execute("PRAGMA foreign_keys=ON;")
            await connection.commit()

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys=ON;")
        yield connection
        await connection.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE;")
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise
            else:
                await connection.commit()

    async def fetchone(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> dict[str, Any] | None:
        if connection is not None:
            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
            await cursor.close()
            return dict(row) if row else None

        async with self.connect() as conn:
            cursor = await conn.execute(query, parameters)
            row = await cursor.fetchone()
            await cursor.close()
            return dict(row) if row else None

    async def fetchall(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if connection is not None:
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
            await cursor.close()
            return [dict(row) for row in rows]

        async with self.connect() as conn:
            cursor = await conn.execute(query, parameters)
            rows = await cursor.fetchall()
            await cursor.close()
            return [dict(row) for row in rows]

    async def execute(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        if connection is not None:
            await connection.execute(query, parameters)
            return

        async with self.connect() as conn:
            await conn.execute(query, parameters)
            await conn.commit()

    async def execute_many(
        self,
        query: str,
        parameters: list[tuple[Any, ...]],
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        if connection is not None:
            await connection.executemany(query, parameters)
            return

        async with self.connect() as conn:
            await conn.executemany(query, parameters)
            await conn.commit()

    def create_backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_connection = sqlite3.connect(self.path)
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()
