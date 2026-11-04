# -*- coding: utf-8 -*-
"""SQLite: баланс пользователей и история платежей."""
import time

import aiosqlite

from config import DB_PATH, FREE_GENERATIONS

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    credits    INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    charge_id  TEXT PRIMARY KEY,   -- telegram_payment_charge_id, уникален
    user_id    INTEGER NOT NULL,
    pack_id    TEXT NOT NULL,
    stars      INTEGER NOT NULL,
    credits    INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    refunded   INTEGER NOT NULL DEFAULT 0
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def ensure_user(user_id: int) -> int:
    """Создаёт пользователя (с бесплатными генерациями) и возвращает баланс."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id, credits, created_at) "
            "VALUES (?, ?, ?)",
            (user_id, FREE_GENERATIONS, int(time.time())),
        )
        await db.commit()
    return await get_balance(user_id)


async def get_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT credits FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
    return row[0] if row else 0


async def spend_credit(user_id: int) -> bool:
    """Атомарно списывает 1 генерацию. False — если баланс пуст."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE users SET credits = credits - 1 "
            "WHERE user_id = ? AND credits > 0",
            (user_id,),
        )
        await db.commit()
        return cur.rowcount == 1


async def add_credits(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET credits = credits + ? WHERE user_id = ?",
            (amount, user_id),
        )
        await db.commit()


async def record_payment(charge_id, user_id, pack_id, stars, credits) -> bool:
    """Сохраняет платёж и начисляет генерации в ОДНОЙ транзакции.

    Возвращает False, если такой charge_id уже был (повторная доставка
    события) — тогда генерации повторно не начисляются.
    """
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO payments"
            "(charge_id, user_id, pack_id, stars, credits, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (charge_id, user_id, pack_id, stars, credits, int(time.time())),
        )
        if cur.rowcount == 0:
            return False
        await db.execute(
            "UPDATE users SET credits = credits + ? WHERE user_id = ?",
            (credits, user_id),
        )
        await db.commit()
        return True


async def get_payment(charge_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM payments WHERE charge_id = ?", (charge_id,)
        )
        return await cur.fetchone()


async def mark_refunded(charge_id: str, user_id: int, credits: int):
    """Помечает платёж возвращённым и забирает купленные генерации."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET refunded = 1 WHERE charge_id = ?",
            (charge_id,),
        )
        await db.execute(
            "UPDATE users SET credits = MAX(credits - ?, 0) "
            "WHERE user_id = ?",
            (credits, user_id),
        )
        await db.commit()
