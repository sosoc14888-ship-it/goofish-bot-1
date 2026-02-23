"""
database.py — работа с SQLite
"""
import json
import aiosqlite
from config import DB_PATH


async def init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL,
                name             TEXT    NOT NULL,
                tags             TEXT    NOT NULL,
                price_min        INTEGER DEFAULT 0,
                price_max        INTEGER DEFAULT 0,
                interval_minutes INTEGER DEFAULT 30,
                active           INTEGER DEFAULT 1,
                image_embedding  TEXT    DEFAULT NULL,
                last_checked     TEXT    DEFAULT (datetime('now')),
                created_at       TEXT    DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_ads (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                search_id INTEGER NOT NULL,
                ad_id     TEXT    NOT NULL,
                found_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE(search_id, ad_id)
            )
        """)
        await db.commit()


async def create_search(user_id, name, tags, price_min, price_max,
                        interval, embedding=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO searches
                (user_id, name, tags, price_min, price_max, interval_minutes, image_embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, name,
            json.dumps(tags, ensure_ascii=False),
            price_min, price_max, interval,
            json.dumps(embedding) if embedding else None
        ))
        await db.commit()


async def get_user_searches(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM searches WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_search(sid: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM searches WHERE id = ?", (sid,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_active_searches() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM searches WHERE active = 1") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def set_active(sid: int, active: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE searches SET active = ? WHERE id = ?",
                         (1 if active else 0, sid))
        await db.commit()


async def delete_search(sid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM searches WHERE id = ?", (sid,))
        await db.execute("DELETE FROM seen_ads WHERE search_id = ?", (sid,))
        await db.commit()


async def mark_seen(search_id: int, ad_id: str) -> bool:
    """Возвращает True если объявление новое"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO seen_ads (search_id, ad_id) VALUES (?, ?)",
                (search_id, str(ad_id))
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def update_checked(sid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE searches SET last_checked = datetime('now') WHERE id = ?", (sid,)
        )
        await db.commit()


async def get_seen_count(search_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM seen_ads WHERE search_id = ?", (search_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0
