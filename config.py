import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PREFIX = os.environ.get("PREFIX", ".")
DB_PATH = os.environ.get("DB_PATH", "data/users.db")
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Tehran")