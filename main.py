import os
import sys
import subprocess
import logging
import warnings

warnings.filterwarnings("ignore")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

CIPHER_REPO = "https://github.com/rishabhops/CipherElite.git"
CIPHER_DIR = os.path.join(os.getcwd(), "CipherElite")


# ── STEP 1: Install CipherElite BEFORE any Telethon imports ──

def install_cipherelite():
    if os.path.isfile(os.path.join(CIPHER_DIR, "main.py")):
        logger.info("CipherElite already present.")
        return True

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
        r2 = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", req],
            capture_output=True,
        )
        if r2.returncode != 0:
            logger.warning(f"Some deps may have failed: {r2.stderr.decode()[-300:]}")

    # Verify Telethon version that CipherElite installed
    r3 = subprocess.run(
        [sys.executable, "-c", "import telethon; print(telethon.__version__)"],
        capture_output=True,
    )
    version = r3.stdout.decode().strip()
    logger.info(f"Telethon version (CipherElite's): {version}")

    if os.path.isfile(os.path.join(CIPHER_DIR, "main.py")):
        logger.info("CipherElite ready!")
        return True

    logger.error("main.py not found after clone!")
    return False


if not install_cipherelite():
    logger.error("FATAL: Could not install CipherElite!")
    sys.exit(1)

# ── STEP 2: NOW import Telethon and our code ──
# At this point, Telethon is CipherElite's version

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
    logger.info("Restoring sessions...")
    n = await manager.restore_all()
    logger.info(f"Restored {n} instance(s)")


async def on_shutdown(app):
    logger.info("=== Shutting down ===")
    await manager.stop_all()


def main():
    if not BOT_TOKEN:
        logger.error("FATAL: BOT_TOKEN is not set!")
        sys.exit(1)

    logger.info("Building application...")
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