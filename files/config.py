"""
config.py — настройки бота
Все переменные берутся из .env файла
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Обязательно ───────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")          # Telegram Bot Token от @BotFather
GOOFISH_COOKIE = os.getenv("GOOFISH_COOKIE", "") # Cookie из браузера Goofish (см. README)

# ─── Доступ (оставь пустым — бот открытый) ─────
_raw = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = set(
    int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()
)

# ─── Переводчик ────────────────────────────────
# "google" — бесплатный (без ключа), "deepl" — точнее (нужен API ключ)
TRANSLATOR = os.getenv("TRANSLATOR", "google")
DEEPL_KEY  = os.getenv("DEEPL_KEY", "")

# ─── AI / CLIP ─────────────────────────────────
# Порог схожести для поиска по фото (0.0 — 1.0)
# 0.25 = умеренно похожи, 0.4 = очень похожи
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.25"))

# ─── Прочее ────────────────────────────────────
DB_PATH     = os.getenv("DB_PATH", "goofish.db")
CNY_TO_RUB  = float(os.getenv("CNY_TO_RUB", "13.5"))  # курс юань → рубль
