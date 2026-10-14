"""Configuration loaded from Railway environment variables; do not hardcode secrets here."""
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

def _parse_admin_ids(value):
    result = []
    for part in value.split(","):
        part = part.strip()
        if part:
            try:
                result.append(int(part))
            except ValueError as exc:
                raise RuntimeError("ADMIN_IDS must be comma-separated numeric Telegram user IDs.") from exc
    return result

ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
if not ADMIN_IDS:
    raise RuntimeError("Set ADMIN_IDS to your Telegram numeric admin ID(s).")

CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_HOLDER = os.getenv("CARD_HOLDER", "").strip()
BRAND_NAME = os.getenv("BRAND_NAME", "VexVPN").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")
