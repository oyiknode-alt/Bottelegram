"""SQLite storage module for the Telegram service-sales bot.
All public functions are async to match bot.py's `await db.*` calls.
"""
import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).with_name("bot_data.sqlite3"))))


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row is not None else None

async def init_db():
    with _connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS gaming_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT, volume_gb INTEGER NOT NULL,
            price INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS multi_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL,
            price INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '', full_name TEXT NOT NULL DEFAULT '',
            plan_id INTEGER, plan_name TEXT NOT NULL, price INTEGER NOT NULL,
            original_price INTEGER NOT NULL, coupon_code TEXT, status TEXT NOT NULL DEFAULT 'awaiting_receipt',
            receipt_file_id TEXT, panel_info TEXT, payment_method TEXT NOT NULL DEFAULT 'receipt',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS wallet_balances (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS wallet_topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '', full_name TEXT NOT NULL DEFAULT '', amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'awaiting_receipt', receipt_file_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY, percent INTEGER NOT NULL, max_uses INTEGER,
            used_count INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE, username TEXT NOT NULL DEFAULT '',
            converted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS referral_commissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL, order_id INTEGER NOT NULL, amount INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        ''')
        defaults = {
            'welcome_message': '', 'rules_text': '', 'referral_commission_percent': '5',
            'wallet_bonus_threshold': '0', 'wallet_bonus_percent': '0'
        }
        c.executemany('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', defaults.items())

async def get_setting(key, default=None):
    with _connect() as c:
        row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

async def set_setting(key, value):
    with _connect() as c:
        c.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))

async def get_welcome_message(): return await get_setting('welcome_message', '')
async def set_welcome_message(text): await set_setting('welcome_message', text)
async def get_rules_text(): return await get_setting('rules_text', '')
async def set_rules_text(text): await set_setting('rules_text', text)
async def get_referral_commission_percent(): return int(await get_setting('referral_commission_percent', '5'))
async def get_wallet_bonus_threshold(): return int(await get_setting('wallet_bonus_threshold', '0'))
async def get_wallet_bonus_percent(): return int(await get_setting('wallet_bonus_percent', '0'))

async def add_gaming_plan(volume_gb, price):
    with _connect() as c: c.execute('INSERT INTO gaming_plans(volume_gb,price) VALUES (?,?)', (int(volume_gb), int(price)))
async def add_multi_plan(label, price):
    with _connect() as c: c.execute('INSERT INTO multi_plans(label,price) VALUES (?,?)', (str(label), int(price)))
async def get_gaming_plans(active_only=True):
    with _connect() as c:
        q='SELECT * FROM gaming_plans' + (' WHERE active=1' if active_only else '') + ' ORDER BY id'
        return [dict(x) for x in c.execute(q).fetchall()]
async def get_multi_plans(active_only=True):
    with _connect() as c:
        q='SELECT * FROM multi_plans' + (' WHERE active=1' if active_only else '') + ' ORDER BY id'
        return [dict(x) for x in c.execute(q).fetchall()]
async def get_gaming_plan(plan_id):
    with _connect() as c: return _dict(c.execute('SELECT * FROM gaming_plans WHERE id=?',(int(plan_id),)).fetchone())
async def get_multi_plan(plan_id):
    with _connect() as c: return _dict(c.execute('SELECT * FROM multi_plans WHERE id=?',(int(plan_id),)).fetchone())
async def toggle_gaming_active(plan_id):
    with _connect() as c: c.execute('UPDATE gaming_plans SET active=1-active WHERE id=?',(int(plan_id),))
async def toggle_multi_active(plan_id):
    with _connect() as c: c.execute('UPDATE multi_plans SET active=1-active WHERE id=?',(int(plan_id),))
async def update_gaming_price(plan_id, price):
    with _connect() as c: c.execute('UPDATE gaming_plans SET price=? WHERE id=?',(int(price),int(plan_id)))
async def update_multi_price(plan_id, price):
    with _connect() as c: c.execute('UPDATE multi_plans SET price=? WHERE id=?',(int(price),int(plan_id)))

async def create_order(user_id, username, full_name, plan_id, plan_name, price):
    with _connect() as c:
        cur=c.execute('INSERT INTO orders(user_id,username,full_name,plan_id,plan_name,price,original_price) VALUES (?,?,?,?,?,?,?)',
                      (int(user_id),username or '',full_name or '',int(plan_id),plan_name,int(price),int(price)))
        return cur.lastrowid
async def get_order(order_id):
    with _connect() as c: return _dict(c.execute('SELECT * FROM orders WHERE id=?',(int(order_id),)).fetchone())
async def get_user_orders(user_id):
    with _connect() as c: return [dict(x) for x in c.execute('SELECT * FROM orders WHERE user_id=? ORDER BY id DESC',(int(user_id),)).fetchall()]
async def set_order_status(order_id, status):
    with _connect() as c: c.execute('UPDATE orders SET status=? WHERE id=?',(str(status),int(order_id)))
async def attach_receipt(order_id, file_id):
    with _connect() as c: c.execute("UPDATE orders SET receipt_file_id=?, status='pending' WHERE id=?",(str(file_id),int(order_id)))
async def mark_order_paid_by_wallet(order_id):
    with _connect() as c: c.execute("UPDATE orders SET payment_method='wallet', status='approved' WHERE id=?",(int(order_id),))
async def deliver_order(order_id, panel_info):
    with _connect() as c: c.execute("UPDATE orders SET panel_info=?, status='delivered' WHERE id=?",(str(panel_info),int(order_id)))

async def get_wallet_balance(user_id):
    with _connect() as c:
        row=c.execute('SELECT balance FROM wallet_balances WHERE user_id=?',(int(user_id),)).fetchone()
        return int(row['balance']) if row else 0
async def add_wallet_balance(user_id, amount):
    with _connect() as c:
        c.execute('INSERT INTO wallet_balances(user_id,balance) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance',(int(user_id),int(amount)))
async def deduct_wallet_balance(user_id, amount):
    with _connect() as c:
        row=c.execute('SELECT balance FROM wallet_balances WHERE user_id=?',(int(user_id),)).fetchone()
        if not row or int(row['balance']) < int(amount): return False
        c.execute('UPDATE wallet_balances SET balance=balance-? WHERE user_id=?',(int(amount),int(user_id)))
        return True
async def create_wallet_topup(user_id, username, full_name, amount):
    with _connect() as c:
        cur=c.execute('INSERT INTO wallet_topups(user_id,username,full_name,amount) VALUES (?,?,?,?)',(int(user_id),username or '',full_name or '',int(amount)))
        return cur.lastrowid
async def get_wallet_topup(topup_id):
    with _connect() as c: return _dict(c.execute('SELECT * FROM wallet_topups WHERE id=?',(int(topup_id),)).fetchone())
async def attach_topup_receipt(topup_id, file_id):
    with _connect() as c: c.execute("UPDATE wallet_topups SET receipt_file_id=?, status='pending' WHERE id=?",(str(file_id),int(topup_id)))
async def set_topup_status(topup_id, status):
    with _connect() as c: c.execute('UPDATE wallet_topups SET status=? WHERE id=?',(str(status),int(topup_id)))

async def get_coupon(code):
    with _connect() as c: return _dict(c.execute('SELECT * FROM coupons WHERE code=?',(str(code).strip().upper(),)).fetchone())
async def create_coupon(code, percent, max_uses):
    with _connect() as c: c.execute('INSERT INTO coupons(code,percent,max_uses) VALUES (?,?,?)',(str(code).strip().upper(),int(percent),None if max_uses is None else int(max_uses)))
async def list_coupons():
    with _connect() as c: return [dict(x) for x in c.execute('SELECT * FROM coupons ORDER BY code').fetchall()]
async def toggle_coupon_active(code):
    with _connect() as c: c.execute('UPDATE coupons SET active=1-active WHERE code=?',(str(code).strip().upper(),))
async def delete_coupon(code):
    with _connect() as c: c.execute('DELETE FROM coupons WHERE code=?',(str(code).strip().upper(),))
async def increment_coupon_usage(code):
    with _connect() as c: c.execute('UPDATE coupons SET used_count=used_count+1 WHERE code=?',(str(code).strip().upper(),))
async def apply_coupon_to_order(order_id, code, new_price):
    with _connect() as c: c.execute('UPDATE orders SET coupon_code=?, price=? WHERE id=?',(str(code).strip().upper(),int(new_price),int(order_id)))
async def remove_coupon_from_order(order_id):
    with _connect() as c: c.execute('UPDATE orders SET coupon_code=NULL, price=original_price WHERE id=?',(int(order_id),))

async def add_referral(referrer_id, referred_id, username=''):
    if int(referrer_id)==int(referred_id): return False
    with _connect() as c:
        try:
            c.execute('INSERT INTO referrals(referrer_id,referred_id,username) VALUES (?,?,?)',(int(referrer_id),int(referred_id),username or ''))
            return True
        except sqlite3.IntegrityError: return False
async def get_referral_by_referred(referred_id):
    with _connect() as c: return _dict(c.execute('SELECT * FROM referrals WHERE referred_id=?',(int(referred_id),)).fetchone())
async def mark_referral_converted(referred_id):
    with _connect() as c: c.execute('UPDATE referrals SET converted=1 WHERE referred_id=?',(int(referred_id),))
async def count_referrals(referrer_id):
    with _connect() as c: return int(c.execute('SELECT COUNT(*) n FROM referrals WHERE referrer_id=?',(int(referrer_id),)).fetchone()['n'])
async def count_converted_referrals(referrer_id):
    with _connect() as c: return int(c.execute('SELECT COUNT(*) n FROM referrals WHERE referrer_id=? AND converted=1',(int(referrer_id),)).fetchone()['n'])
async def get_total_referral_earnings(referrer_id):
    with _connect() as c: return int(c.execute('SELECT COALESCE(SUM(amount),0) n FROM referral_commissions WHERE referrer_id=?',(int(referrer_id),)).fetchone()['n'])
async def add_referral_commission(referrer_id, referred_id, order_id, amount):
    with _connect() as c: c.execute('INSERT INTO referral_commissions(referrer_id,referred_id,order_id,amount) VALUES (?,?,?,?)',(int(referrer_id),int(referred_id),int(order_id),int(amount)))



async def get_sales_stats():
    with _connect() as c:
        total_orders = c.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        total_users = c.execute(
            "SELECT COUNT(DISTINCT user_id) FROM orders"
        ).fetchone()[0]

        pending_orders = c.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN ('awaiting_receipt','pending')"
        ).fetchone()[0]

        approved_count = c.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN ('approved','delivered')"
        ).fetchone()[0]

        wallet_count = c.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_method='wallet' AND status IN ('approved','delivered')"
        ).fetchone()[0]

        wallet_revenue = c.execute(
            "SELECT COALESCE(SUM(price),0) FROM orders WHERE payment_method='wallet' AND status IN ('approved','delivered')"
        ).fetchone()[0]

        revenue_today = c.execute("""
            SELECT COALESCE(SUM(price),0) FROM orders
            WHERE status IN ('approved','delivered')
            AND date(created_at, 'localtime') = date('now','localtime')
        """).fetchone()[0]

        revenue_week = c.execute("""
            SELECT COALESCE(SUM(price),0) FROM orders
            WHERE status IN ('approved','delivered')
            AND date(created_at, 'localtime') >= date('now','localtime','-6 days')
        """).fetchone()[0]

        revenue_month = c.execute("""
            SELECT COALESCE(SUM(price),0) FROM orders
            WHERE status IN ('approved','delivered')
            AND strftime('%Y-%m', created_at, 'localtime') = strftime('%Y-%m','now','localtime')
        """).fetchone()[0]

        daily = c.execute("""
            SELECT date(created_at, 'localtime') AS day,
                   COALESCE(SUM(price),0) AS revenue
            FROM orders
            WHERE status IN ('approved','delivered')
              AND date(created_at, 'localtime') >= date('now','localtime','-6 days')
            GROUP BY date(created_at, 'localtime')
            ORDER BY day
        """).fetchall()

        best_plans = c.execute("""
            SELECT plan_name, COUNT(*) AS quantity, COALESCE(SUM(price),0) AS revenue
            FROM orders
            WHERE status IN ('approved','delivered')
            GROUP BY plan_name
            ORDER BY quantity DESC, revenue DESC
            LIMIT 5
        """).fetchall()

        return {
            'total_orders': total_orders,
            'total_users': total_users,
            'pending_orders': pending_orders,
            'approved_count': approved_count,
            'wallet_count': wallet_count,
            'wallet_revenue': wallet_revenue,
            'revenue_today': revenue_today,
            'revenue_week': revenue_week,
            'revenue_month': revenue_month,
            'daily': [dict(x) for x in daily],
            'best_plans': [dict(x) for x in best_plans],
        }


# ---------- Report tracking users ----------
async def get_user(user_id):
    with _connect() as c:
        row = c.execute(
            'SELECT user_id FROM report_users WHERE user_id=?',
            (user_id,)
        ).fetchone()
        return _dict(row)


async def touch_user(user_id, username='', full_name=''):
    with _connect() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS report_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                full_name TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            INSERT INTO report_users(user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                last_seen=CURRENT_TIMESTAMP
        ''', (user_id, username, full_name))
