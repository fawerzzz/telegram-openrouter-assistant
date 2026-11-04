from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import os


@dataclass(slots=True)
class Reminder:
    id: int
    user_id: int
    chat_id: int
    thread_id: int
    reminder_text: str
    trigger_time: str
    is_sent: int


class Database:
    def __init__(self):
        self.pool = None


    async def init(self) -> None:
        self.pool = await asyncpg.create_pool(
            dsn=os.getenv("DATABASE_URL")
        )

        async with self.pool.acquire() as connection:
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    context_key TEXT NOT NULL,
                    thread_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            await connection.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    reminder_text TEXT NOT NULL,
                    trigger_time TEXT NOT NULL,
                    is_sent INTEGER NOT NULL DEFAULT 0
                )
            """)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def add_message(
        self,
        context_key: str,
        role: str,
        content: str,
        thread_id: int = 0
    ) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute("""
                INSERT INTO messages (
                    context_key, thread_id, role, content, timestamp
                )
                VALUES ($1, $2, $3, $4, $5)
            """,
                context_key,
                thread_id,
                role,
                content,
                datetime.now().isoformat(timespec="seconds")
            )

    async def get_history(
        self,
        context_key: str,
        limit: int = 10
    ) -> list[dict[str, str]]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch("""
                SELECT role, content
                FROM messages
                WHERE context_key = $1
                ORDER BY id DESC
                LIMIT $2
            """, context_key, limit)

        rows = reversed(rows)

        return [
            {
                "role": row["role"],
                "content": row["content"]
            }
            for row in rows
        ]

    async def add_reminder(
        self,
        user_id: int,
        chat_id: int,
        thread_id: int,
        reminder_text: str,
        trigger_time: datetime
    ) -> int:
        async with self.pool.acquire() as connection:
            reminder_id = await connection.fetchval("""
                INSERT INTO reminders (
                    user_id,
                    chat_id,
                    thread_id,
                    reminder_text,
                    trigger_time
                )
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """,
                user_id,
                chat_id,
                thread_id,
                reminder_text,
                trigger_time.isoformat(timespec="seconds")
            )

        return reminder_id

    async def mark_reminder_sent(self, reminder_id: int) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute("""
                UPDATE reminders
                SET is_sent = 1
                WHERE id = $1
            """, reminder_id)

    async def get_pending_reminders(self) -> list[Reminder]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch("""
                SELECT *
                FROM reminders
                WHERE is_sent = 0
            """)

        return [
            Reminder(**dict(row))
            for row in rows
        ]

    async def get_due_reminders(
        self,
        now: datetime
    ) -> list[Reminder]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch("""
                SELECT *
                FROM reminders
                WHERE is_sent = 0
                AND trigger_time <= $1
            """, now.isoformat(timespec="seconds"))

        return [
            Reminder(**dict(row))
            for row in rows
        ]


def rows_to_openrouter_messages(
    rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "role": row["role"],
            "content": row["content"]
        }
        for row in rows
    ]