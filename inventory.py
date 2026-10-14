import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).with_name("bot_data.sqlite3"))))


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_inventory():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_type TEXT NOT NULL,
                plan_name TEXT NOT NULL,
                volume_gb INTEGER,
                config_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                order_id INTEGER UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS free_test_claims (
                user_id INTEGER PRIMARY KEY,
                config_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'reserved',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def add_config(plan_type, plan_name, volume_gb, config_text):
    with connect() as conn:
        cur = conn.execute("""
            INSERT INTO configs (plan_type, plan_name, volume_gb, config_text)
            VALUES (?, ?, ?, ?)
        """, (plan_type, plan_name, volume_gb, config_text))
        return cur.lastrowid


def list_configs(status=None):
    with connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM configs WHERE status=? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM configs ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]


def delete_config(config_id):
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM configs WHERE id=? AND status='available'", (int(config_id),)
        )
        return cur.rowcount > 0


def reserve_config(order_id, plan_type, plan_name, volume_gb=None):
    """Atomically reserve a matching config, idempotently per order."""
    order_id = int(order_id)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM configs WHERE order_id=?", (order_id,)
        ).fetchone()
        if existing:
            if existing["status"] in ("reserved", "sold"):
                return dict(existing)
            return None

        if plan_type == "gaming":
            # Gaming plans are matched by exact volume; the inventory display name is free text.
            row = conn.execute("""
                SELECT * FROM configs
                WHERE status='available' AND plan_type='gaming' AND volume_gb=?
                ORDER BY id LIMIT 1
            """, (int(volume_gb),)).fetchone()
        elif plan_type == "multi":
            # Multi-location inventory name must equal the plan label in database.py.
            row = conn.execute("""
                SELECT * FROM configs
                WHERE status='available' AND plan_type='multi' AND plan_name=?
                ORDER BY id LIMIT 1
            """, (str(plan_name),)).fetchone()
        else:
            return None

        if not row:
            return None
        cur = conn.execute("""
            UPDATE configs SET status='reserved', order_id=?
            WHERE id=? AND status='available' AND order_id IS NULL
        """, (order_id, row["id"]))
        if cur.rowcount != 1:
            return None
        result = conn.execute("SELECT * FROM configs WHERE id=?", (row["id"],)).fetchone()
        return dict(result)


def mark_config_sold(order_id):
    with connect() as conn:
        cur = conn.execute("""
            UPDATE configs SET status='sold'
            WHERE order_id=? AND status='reserved'
        """, (int(order_id),))
        return cur.rowcount == 1


def release_config(order_id):
    """Release only an undelivered reservation; sold configs cannot be released."""
    with connect() as conn:
        cur = conn.execute("""
            UPDATE configs SET status='available', order_id=NULL
            WHERE order_id=? AND status='reserved'
        """, (int(order_id),))
        return cur.rowcount == 1


def has_free_test_claim(user_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM free_test_claims WHERE user_id=?", (int(user_id),)
        ).fetchone()
        return row is not None


def reserve_free_test(user_id):
    """Atomically reserve one test config for a user who has never claimed one."""
    user_id = int(user_id)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        already = conn.execute(
            "SELECT 1 FROM free_test_claims WHERE user_id=?", (user_id,)
        ).fetchone()
        if already:
            return None
        row = conn.execute(
            "SELECT * FROM configs WHERE plan_type='test' AND status='available' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        cur = conn.execute(
            "UPDATE configs SET status='reserved', order_id=? WHERE id=? AND status='available'",
            (-user_id, row["id"]),
        )
        if cur.rowcount != 1:
            return None
        conn.execute(
            "INSERT INTO free_test_claims (user_id, config_id, status) VALUES (?, ?, 'reserved')",
            (user_id, row["id"]),
        )
        result = conn.execute("SELECT * FROM configs WHERE id=?", (row["id"],)).fetchone()
        return dict(result)


def complete_free_test(user_id):
    user_id = int(user_id)
    with connect() as conn:
        claim = conn.execute(
            "SELECT config_id FROM free_test_claims WHERE user_id=? AND status='reserved'",
            (user_id,),
        ).fetchone()
        if not claim:
            return False
        conn.execute(
            "UPDATE configs SET status='sold' WHERE id=? AND status='reserved'",
            (claim["config_id"],),
        )
        conn.execute(
            "UPDATE free_test_claims SET status='delivered' WHERE user_id=?", (user_id,)
        )
        return True


def release_free_test(user_id):
    """Release a test config only if delivery failed, allowing a retry."""
    user_id = int(user_id)
    with connect() as conn:
        claim = conn.execute(
            "SELECT config_id FROM free_test_claims WHERE user_id=? AND status='reserved'",
            (user_id,),
        ).fetchone()
        if not claim:
            return False
        conn.execute(
            "UPDATE configs SET status='available', order_id=NULL WHERE id=? AND status='reserved'",
            (claim["config_id"],),
        )
        conn.execute("DELETE FROM free_test_claims WHERE user_id=?", (user_id,))
        return True

