"""Forum-topic reporting add-on for the X4G Telegram sales bot.
Uses existing database settings and inventory module; never reports config contents.
"""
import asyncio
import html
import logging
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from database import DB_PATH

TOPICS = {
    "users": "👥 شروع کاربران",
    "sales": "💰 فروش و تحویل",
    "stock": "📦 موجودی انبار",
    "errors": "🚨 خطاها و هشدارها",
    "daily": "📊 گزارش روزانه",
    "admin": "🛠 عملیات مدیریتی",
}
TZ = ZoneInfo("Asia/Tehran")


async def send_report(bot, db, topic_key, text):
    """Send a report into its forum topic. Reporting failures never break bot flows."""
    try:
        chat_id = await db.get_setting("reports_chat_id")
        thread_id = await db.get_setting(f"reports_topic_{topic_key}")
        if not chat_id or not thread_id:
            return False
        await bot.send_message(
            int(chat_id), text, message_thread_id=int(thread_id), parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        logging.exception("Could not send forum report (%s)", topic_key)
        return False


async def setup_forum(bot, db, chat_id):
    """Create and persist report topics; can be safely retried after partial failure."""
    chat = await bot.get_chat(chat_id)
    if getattr(chat, "type", None) not in ("supergroup", "group"):
        raise RuntimeError("این دستور باید داخل گروه اجرا شود.")
    if not getattr(chat, "is_forum", False):
        raise RuntimeError("موضوعات گروه فعال نیست. در تنظیمات گروه، Topics/موضوعات را روشن کن و دوباره دستور بده.")

    me = await bot.get_me()
    member = await bot.get_chat_member(chat_id, me.id)
    status = getattr(member, "status", "")
    if status not in ("administrator", "creator"):
        raise RuntimeError("ربات هنوز ادمین گروه نیست.")
    if hasattr(member, "can_manage_topics") and not member.can_manage_topics:
        raise RuntimeError("به ربات دسترسی مدیریت موضوعات بده (Manage Topics) و دوباره تلاش کن.")

    await db.set_setting("reports_chat_id", str(chat_id))
    created, existing = [], []
    for key, name in TOPICS.items():
        saved_id = await db.get_setting(f"reports_topic_{key}")
        if saved_id:
            existing.append(name)
            continue
        topic = await bot.create_forum_topic(chat_id, name)
        thread_id = getattr(topic, "message_thread_id", None)
        if not thread_id:
            raise RuntimeError(f"تاپیک «{name}» ساخته شد ولی شناسه‌اش دریافت نشد. دستور را دوباره اجرا کن.")
        await db.set_setting(f"reports_topic_{key}", str(thread_id))
        created.append(name)

    await send_report(
        bot, db, "admin",
        "✅ <b>مرکز گزارش‌گیری فعال شد</b>\n"
        f"🆔 شناسه گروه: <code>{chat_id}</code>\n"
        f"📚 تاپیک‌های تازه ساخته‌شده: {len(created)}\n"
        "📡 گزارش شروع کاربران، فروش/تحویل، موجودی، خطاها و خلاصه روزانه از این به بعد اینجا ثبت می‌شود.",
    )
    return created, existing


def _stock_counts(inv):
    rows = inv.list_configs()
    counts = {}
    for row in rows:
        kind = str(row.get("plan_type") or "other")
        status = str(row.get("status") or "unknown")
        counts.setdefault(kind, {}).setdefault(status, 0)
        counts[kind][status] += 1
    return counts


def stock_text(inv):
    labels = {"gaming": "🎮 گیمینگ", "multi": "🌍 مولتی‌لوکیشن", "test": "🔋 تست رایگان"}
    counts = _stock_counts(inv)
    lines = ["📦 <b>وضعیت موجودی مخزن</b>"]
    for kind in ("gaming", "multi", "test"):
        group = counts.get(kind, {})
        available = group.get("available", 0)
        reserved = group.get("reserved", 0)
        sold = group.get("sold", 0)
        lines.append(f"{labels[kind]}: موجود <b>{available}</b> | رزرو <b>{reserved}</b> | تحویل‌شده <b>{sold}</b>")
    return "\n".join(lines)


async def send_stock_report(bot, db, inv, alert_if_empty=False, kind=None):
    try:
        counts = _stock_counts(inv)
        if alert_if_empty and kind and counts.get(kind, {}).get("available", 0) > 0:
            return
        text = stock_text(inv)
        if alert_if_empty:
            label = {"gaming": "گیمینگ", "multi": "مولتی‌لوکیشن", "test": "تست رایگان"}.get(kind, kind)
            text = f"🚨 <b>هشدار کمبود/اتمام موجودی</b>\nنوع: {html.escape(str(label))}\n\n" + text
            await send_report(bot, db, "errors", text)
        else:
            await send_report(bot, db, "stock", text)
    except Exception:
        logging.exception("Could not create inventory report")


async def daily_report(bot, db, inv):
    """Read real SQLite data for a daily summary; all monetary values are toman."""
    try:
        today = datetime.now(TZ).date().isoformat()
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            total_users = conn.execute("SELECT COUNT(*) FROM report_users").fetchone()[0]
            new_users = conn.execute(
                "SELECT COUNT(*) FROM report_users WHERE substr(joined_at,1,10)=?", (today,)
            ).fetchone()[0]
            order_rows = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(price),0) AS revenue FROM orders "
                "WHERE substr(COALESCE(created_at,''),1,10)=? AND status IN ('approved','delivered')",
                (today,),
            ).fetchone()
            pending = conn.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
        text = (
            "📊 <b>گزارش روزانه ربات</b>\n"
            f"📅 تاریخ: {today}\n\n"
            f"👥 کل کاربران ثبت‌شده: <b>{total_users:,}</b>\n"
            f"🆕 شروع‌های جدید امروز: <b>{new_users:,}</b>\n"
            f"🛒 سفارش‌های تأیید/تحویل‌شده امروز: <b>{order_rows['n']:,}</b>\n"
            f"💰 مبلغ سفارش‌های موفق امروز: <b>{int(order_rows['revenue']):,} تومان</b>\n"
            f"⏳ سفارش‌های در انتظار: <b>{pending:,}</b>\n\n"
            + stock_text(inv)
        )
        await send_report(bot, db, "daily", text)
    except Exception:
        logging.exception("Daily forum report failed")
        await send_report(bot, db, "errors", "🚨 <b>خطا در ساخت گزارش روزانه</b>\nجزئیات کامل در لاگ سرویس ثبت شده است.")


async def daily_report_loop(bot, db, inv):
    """Post one daily report at 09:00 Tehran time, including after restarts."""
    while True:
        now = datetime.now(TZ)
        target = datetime.combine(now.date(), time(hour=9), tzinfo=TZ)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep(max(1, (target - now).total_seconds()))
        await daily_report(bot, db, inv)

