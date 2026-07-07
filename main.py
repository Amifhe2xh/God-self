import logging
import sys
import warnings

# Suppress noisy warnings
warnings.filterwarnings("ignore", message=r".*CallbackQueryHandler.*")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from telegram.ext import Application
from config import BOT_TOKEN
from database import Database
from cipher_manager import CipherManager
from handlers import BotHandlers

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

db = Database()
manager = CipherManager(db)


async def on_startup(app):
    logger.info("=== CipherElite Deployer Bot Starting ===")

    logger.info("Checking CipherElite installation...")
    ready = await manager.ensure_cipherelite()

    if not ready:
        logger.error("FATAL: Could not install CipherElite!")
        sys.exit(1)

    logger.info("Restoring user sessions...")
    n = await manager.restore_all()
    logger.info(f"Restored {n} instance(s)")
    logger.info("=== Bot Ready! ===")


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