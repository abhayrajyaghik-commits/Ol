import asyncpg
import os
import json
import random
from typing import List, Optional
from datetime import datetime, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL not set in environment variables!")
        self.pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=20
        )

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def execute(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)


db = Database()


# =========================
# TABLE SETUP
# =========================

async def create_tables():
    await db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        is_premium BOOLEAN DEFAULT FALSE,
        premium_days INT DEFAULT 0,
        added_by TEXT DEFAULT 'admin',
        expiry TIMESTAMP,
        is_banned BOOLEAN DEFAULT FALSE,
        banned_at TIMESTAMP,
        banned_by BIGINT
    );
    """)

    await db.execute("""
    CREATE TABLE IF NOT EXISTS proxies (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        ip TEXT NOT NULL,
        port TEXT NOT NULL,
        username TEXT,
        password TEXT,
        proxy_url TEXT NOT NULL,
        proxy_type TEXT DEFAULT 'http'
    );
    """)

    await db.execute("""
    CREATE TABLE IF NOT EXISTS sites (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        site TEXT NOT NULL,
        UNIQUE(user_id, site)
    );
    """)

    await db.execute("""
    CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY,
        days INT NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        used BOOLEAN DEFAULT FALSE,
        used_by BIGINT,
        used_at TIMESTAMP
    );
    """)

    await db.execute("""
    CREATE TABLE IF NOT EXISTS approved_cards (
        id SERIAL PRIMARY KEY,
        card TEXT NOT NULL,
        status TEXT NOT NULL,
        response TEXT,
        gateway TEXT,
        price TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)


# =========================
# USER SYSTEM
# =========================

async def ensure_user(user_id: int):
    await db.execute("""
        INSERT INTO users (user_id)
        VALUES ($1)
        ON CONFLICT (user_id) DO NOTHING
    """, user_id)


async def get_user(user_id: int):
    return await db.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)


async def is_premium_user(user_id: int) -> bool:
    user = await get_user(user_id)
    if not user:
        return False
    if user["is_premium"] and user["expiry"]:
        if user["expiry"] < datetime.utcnow():
            await remove_premium(user_id)
            return False
        return True
    return False


async def add_premium_user(user_id: int, days: int):
    await ensure_user(user_id)
    expiry = datetime.utcnow() + timedelta(days=days)
    await db.execute("""
        UPDATE users
        SET is_premium = TRUE, expiry = $2, premium_days = $3, added_by = 'admin'
        WHERE user_id = $1
    """, user_id, expiry, days)


async def remove_premium(user_id: int) -> bool:
    await ensure_user(user_id)
    result = await db.execute("""
        UPDATE users
        SET is_premium = FALSE, expiry = NULL, premium_days = 0
        WHERE user_id = $1 AND is_premium = TRUE
    """, user_id)
    return result != "UPDATE 0"


async def is_banned_user(user_id: int) -> bool:
    user = await get_user(user_id)
    if not user:
        return False
    return user["is_banned"]


async def ban_user(user_id: int, banned_by: int):
    await ensure_user(user_id)
    await db.execute("""
        UPDATE users
        SET is_banned = TRUE, banned_at = $2, banned_by = $3
        WHERE user_id = $1
    """, user_id, datetime.utcnow(), banned_by)


async def unban_user(user_id: int) -> bool:
    result = await db.execute("""
        UPDATE users
        SET is_banned = FALSE, banned_at = NULL, banned_by = NULL
        WHERE user_id = $1 AND is_banned = TRUE
    """, user_id)
    return result != "UPDATE 0"


# =========================
# KEY SYSTEM
# =========================

async def create_key(key: str, days: int):
    await db.execute("""
        INSERT INTO keys (key, days, created_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (key) DO NOTHING
    """, key, days, datetime.utcnow())


async def get_key_data(key: str):
    return await db.fetchrow("SELECT * FROM keys WHERE key = $1", key)


async def use_key(user_id: int, key: str):
    row = await db.fetchrow("SELECT * FROM keys WHERE key = $1", key)
    if not row:
        return False, "Invalid key!"
    if row["used"]:
        return False, "This key has already been used!"
    await db.execute("""
        UPDATE keys SET used = TRUE, used_by = $1, used_at = $2 WHERE key = $3
    """, user_id, datetime.utcnow(), key)
    await add_premium_user(user_id, row["days"])
    return True, row["days"]


async def get_all_keys():
    return await db.fetch("SELECT * FROM keys ORDER BY created_at DESC")


# =========================
# PROXY SYSTEM
# =========================

async def add_proxy_db(user_id: int, proxy_data: dict):
    await db.execute("""
        INSERT INTO proxies (user_id, ip, port, username, password, proxy_url, proxy_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, user_id, proxy_data['ip'], proxy_data['port'],
        proxy_data.get('username'), proxy_data.get('password'),
        proxy_data['proxy_url'], proxy_data.get('type', 'http'))


async def get_all_user_proxies(user_id: int) -> list:
    rows = await db.fetch("""
        SELECT id, ip, port, username, password, proxy_url, proxy_type
        FROM proxies WHERE user_id = $1 ORDER BY id
    """, user_id)
    return [dict(r) for r in rows]


async def get_proxy_count(user_id: int) -> int:
    val = await db.fetchval("SELECT COUNT(*) FROM proxies WHERE user_id = $1", user_id)
    return val or 0


async def get_random_proxy(user_id: int):
    row = await db.fetchrow("""
        SELECT ip, port, username, password, proxy_url, proxy_type
        FROM proxies WHERE user_id = $1
        ORDER BY RANDOM() LIMIT 1
    """, user_id)
    if row:
        return dict(row)
    return None


async def remove_proxy_by_index(user_id: int, index: int):
    rows = await db.fetch("""
        SELECT id, ip, port FROM proxies WHERE user_id = $1 ORDER BY id
    """, user_id)
    if index < 0 or index >= len(rows):
        return None
    row = rows[index]
    await db.execute("DELETE FROM proxies WHERE id = $1", row['id'])
    return dict(row)


async def remove_proxy_by_url(user_id: int, proxy_url: str):
    await db.execute("DELETE FROM proxies WHERE user_id = $1 AND proxy_url = $2", user_id, proxy_url)


async def clear_all_proxies(user_id: int) -> int:
    count = await get_proxy_count(user_id)
    await db.execute("DELETE FROM proxies WHERE user_id = $1", user_id)
    return count


# =========================
# SITE SYSTEM
# =========================

async def add_site_db(user_id: int, site: str) -> bool:
    try:
        await db.execute("INSERT INTO sites (user_id, site) VALUES ($1, $2)", user_id, site)
        return True
    except Exception:
        return False


async def get_user_sites(user_id: int) -> list:
    rows = await db.fetch("SELECT site FROM sites WHERE user_id = $1 ORDER BY id", user_id)
    return [r["site"] for r in rows]


async def remove_site_db(user_id: int, site: str) -> bool:
    result = await db.execute("DELETE FROM sites WHERE user_id = $1 AND site = $2", user_id, site)
    return result != "DELETE 0"


async def clear_user_sites(user_id: int):
    await db.execute("DELETE FROM sites WHERE user_id = $1", user_id)


async def set_user_sites(user_id: int, sites: list):
    await clear_user_sites(user_id)
    for site in sites:
        await add_site_db(user_id, site)


# =========================
# APPROVED CARDS
# =========================

async def save_card_to_db(card: str, status: str, response: str, gateway: str, price: str):
    await db.execute("""
        INSERT INTO approved_cards (card, status, response, gateway, price, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, card, status, response or '', gateway or '', price or '', datetime.utcnow())


async def get_total_cards_count():
    return await db.fetchval("SELECT COUNT(*) FROM approved_cards") or 0


async def get_charged_count():
    return await db.fetchval("SELECT COUNT(*) FROM approved_cards WHERE status = 'CHARGED'") or 0


async def get_approved_count():
    return await db.fetchval("SELECT COUNT(*) FROM approved_cards WHERE status = 'APPROVED'") or 0


# =========================
# STATS HELPERS
# =========================

async def get_all_premium_users():
    return await db.fetch("SELECT * FROM users WHERE is_premium = TRUE ORDER BY expiry")


async def get_total_users():
    return await db.fetchval("SELECT COUNT(*) FROM users") or 0


async def get_premium_count():
    return await db.fetchval("SELECT COUNT(*) FROM users WHERE is_premium = TRUE") or 0


async def get_total_sites_count():
    return await db.fetchval("SELECT COUNT(*) FROM sites") or 0


async def get_users_with_sites():
    return await db.fetchval("SELECT COUNT(DISTINCT user_id) FROM sites") or 0


async def get_sites_per_user():
    return await db.fetch("SELECT user_id, COUNT(*) as cnt FROM sites GROUP BY user_id ORDER BY cnt DESC")


async def get_all_sites_detail():
    return await db.fetch("SELECT user_id, site FROM sites ORDER BY user_id, id")


# =========================
# INIT
# =========================

async def init_db():
    await db.connect()
    await create_tables()
    print("✅ Database connected and tables created!")
