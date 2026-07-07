import os
import sys
import subprocess
import logging
import warnings

warnings.filterwarnings("ignore")

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

CIPHER_REPO = "https://github.com/rishabhops/CipherElite.git"
CIPHER_DIR = os.path.join(os.getcwd(), "CipherElite")


def install_cipherelite():
    if os.path.isfile(os.path.join(CIPHER_DIR, "main.py")):
        logger.info("CipherElite already present.")
    else:
        logger.info("Cloning CipherElite...")
        r = subprocess.run(
            ["git", "clone", "--depth=1", CIPHER_REPO, CIPHER_DIR],
            capture_output=True,
        )
        if r.returncode != 0:
            logger.error(f"Clone failed: {r.stderr.decode()[-300:]}")
            return False

    req = os.path.join(CIPHER_DIR, "requirements.txt")
    if os.path.isfile(req):
        logger.info("Installing CipherElite dependencies...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", req],
            capture_output=True,
        )

    r = subprocess.run(
        [sys.executable, "-c", "import telethon; print(telethon.__version__)"],
        capture_output=True,
    )
    ver = r.stdout.decode().strip()
    logger.info(f"Telethon version: {ver}")

    if os.path.isfile(os.path.join(CIPHER_DIR, "main.py")):
        logger.info("CipherElite ready!")
        return True

    logger.error("main.py not found!")
    return False


if not install_cipherelite():
    logger.error("FATAL: Could not install CipherElite!")
    sys.exit(1)

# NOW import — uses same Telethon as CipherElite
from config import BOT_TOKEN
from database import Database
from cipher_manager import CipherManager
from handlers import BotHandlers
from telegram.ext import Application

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

db = Database()
manager = CipherManager(db)


async def on_startup(app):
    logger.info("=== Bot Ready ===")
    n = await manager.restore_all()
    logger.info(f"Restored {n} instance(s)")


async def on_shutdown(app):
    await manager.stop_all()


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing!")
        sys.exit(1)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    handlers = BotHandlers(db, manager)
    handlers.setup(app)

    logger.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()