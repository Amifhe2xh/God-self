import os
import logging
import base64
from warnings import filterwarnings

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    ApiIdInvalidError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    FloodWaitError,
)

from database import Database
from cipher_manager import CipherManager

filterwarnings(
    "ignore",
    message=r".*CallbackQueryHandler.*",
    category=PTBUserWarning,
)

logger = logging.getLogger(__name__)

API_ID, API_HASH, PHONE, CODE, TWO_FA, PREFIX_STEP = range(6)

SESSION_DIR = os.path.join(os.getcwd(), "data", "sessions")


def fix_base64(s: str) -> str:
    s = s.strip().replace("\n", "").replace("\r", "").replace(" ", "")
    missing = len(s) % 4
    if missing:
        s += "=" * (4 - missing)
    return s


class BotHandlers:
    def __init__(self, db: Database, manager: CipherManager):
        self.db = db
        self.manager = manager
        self.temp: dict[int, dict] = {}

    # ── /start ───────────────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        logger.info(f"/start from {uid}")
        existing = self.db.get_user(uid)

        if existing and existing["is_active"] and self.manager.is_running(uid):
            status = "🟢 فعال"
        elif existing and existing["is_active"]:
            status = "🟡 ذخیره شده"
        else:
            status = "🔴 غیرفعال"

        name = update.effective_user.first_name or "کاربر"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 نصب CipherElite", callback_data="setup")],
            [
                InlineKeyboardButton("📊 وضعیت", callback_data="status"),
                InlineKeyboardButton("⏹ توقف", callback_data="stop"),
            ],
            [
                InlineKeyboardButton("🔄 ری‌استارت", callback_data="restart"),
                InlineKeyboardButton("🗑 حذف", callback_data="delete"),
            ],
            [InlineKeyboardButton("📚 راهنما", callback_data="help")],
        ])

        text = (
            f"🔷 <b>CipherElite Deployer</b>\n\n"
            f"سلام <b>{name}</b>!\n\n"
            f"📊 وضعیت: {status}\n\n"
            f"• هوش مصنوعی داخلی\n"
            f"• ۶۰+ پلاگین\n"
            f"• ری‌استارت خودکار\n\n"
            f"⚠️ مسئولیت استفاده بر عهده شماست."
        )

        await update.message.reply_text(
            text, reply_markup=kb, parse_mode="HTML"
        )

    # ── standalone buttons ───────────────────────────────────

    async def btn_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        logger.info(f"[btn_status] user={q.from_user.id}")
        user = self.db.get_user(q.from_user.id)

        if user and user["is_active"]:
            r = self.manager.is_running(q.from_user.id)
            icon = "🟢 فعال" if r else "🟡 متوقف"
            text = (
                f"📊 <b>وضعیت</b>\n\n"
                f"شماره: <code>+{user['phone']}</code>\n"
                f"API: <code>{user['api_id']}</code>\n"
                f"پیشوند: <code>{user['prefix']}</code>\n"
                f"وضعیت: {icon}"
            )
        else:
            text = "❌ نصب نشده."

        await q.message.reply_text(text, parse_mode="HTML")

    async def btn_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        logger.info(f"[btn_stop] user={uid}")
        await self.manager.stop_instance(uid)
        self.db.deactivate_user(uid)
        await q.message.reply_text("⏹ متوقف شد.")

    async def btn_restart(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        logger.info(f"[btn_restart] user={uid}")
        user = self.db.get_user(uid)

        if not user:
            return await q.message.reply_text("❌ ابتدا نصب کنید.")

        msg = await q.message.reply_text("🔄 ری‌استارت...")

        ok = await self.manager.start_instance(
            uid, user["api_id"], user["api_hash"],
            user["session_string"], user.get("prefix", "."),
        )

        await msg.edit_text("✅ شد!" if ok else "❌ خطا")

    async def btn_delete(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        logger.info(f"[btn_delete] user={uid}")
        await self.manager.stop_instance(uid)
        self.db.deactivate_user(uid)

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ بله", callback_data="confirm_delete"),
                InlineKeyboardButton("❌ نه", callback_data="cancel_delete"),
            ]
        ])
        await q.message.reply_text("⚠️ حذف شود؟", reply_markup=kb)

    async def btn_confirm_delete(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        logger.info(f"[btn_confirm_delete] user={uid}")
        with self.db._conn() as conn:
            conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
        await q.message.reply_text("🗑 حذف شد. /start")

    async def btn_cancel_delete(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        await q.message.reply_text("✅ لغو شد.")

    async def btn_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        text = (
            "📚 <b>راهنما</b>\n\n"
            "1. از my.telegram.org API بگیرید\n"
            "2. نصب CipherElite بزنید\n"
            "3. اطلاعات را وارد کنید\n"
            "4. تمام!\n\n"
            "دستورات:\n"
            "<code>.help</code> <code>.ping</code> <code>.alive</code>"
        )
        await q.message.reply_text(text, parse_mode="HTML")

    # ── setup entry ──────────────────────────────────────────

    async def setup_entry(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        uid = q.from_user.id
        logger.info(f"[SETUP] clicked by {uid}")

        await q.answer("⏳")

        if self.manager.is_running(uid):
            await q.message.reply_text("⚠️ از قبل فعال است!")
            return ConversationHandler.END

        self.temp.pop(uid, None)

        await q.message.reply_text(
            "🔷 <b>مرحله ۱ از ۶ — API_ID</b>\n\n"
            "از my.telegram.org بگیرید.\n\n"
            "/cancel = لغو",
            parse_mode="HTML",
        )
        return API_ID

    # ── conversation steps ───────────────────────────────────

    async def rx_api_id(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = update.message.text.strip()
        logger.info(f"[API_ID] user={uid} text={text}")

        try:
            api_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ عدد صحیح وارد کنید.")
            return API_ID

        self.temp[uid] = {"api_id": api_id}

        await update.message.reply_text(
            "🔷 <b>مرحله ۲ از ۶ — API_HASH</b>\n\nبفرستید:",
            parse_mode="HTML",
        )
        return API_HASH

    async def rx_api_hash(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        h = update.message.text.strip()
        logger.info(f"[API_HASH] user={uid}")

        if len(h) < 20:
            await update.message.reply_text("❌ نامعتبر.")
            return API_HASH

        self.temp[uid]["api_hash"] = h
        await update.message.reply_text(
            "🔷 <b>مرحله ۳ از ۶ — شماره تلفن</b>\n\n"
            "مثال: <code>+989123456789</code>",
            parse_mode="HTML",
        )
        return PHONE

    async def rx_phone(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        phone = update.message.text.strip().replace(" ", "")
        data = self.temp[uid]
        logger.info(f"[PHONE] user={uid} phone={phone}")

        msg = await update.message.reply_text("⏳ اتصال...")

        try:
            # Use file session for stability
            os.makedirs(SESSION_DIR, exist_ok=True)
            session_path = os.path.join(SESSION_DIR, str(uid))

            client = TelegramClient(
                session_path, data["api_id"], data["api_hash"],
                connection_retries=5, retry_delay=1,
            )
            await client.connect()
            await client.send_code_request(phone)

            data["phone"] = phone
            data["client"] = client
            data["session_path"] = session_path

            await msg.edit_text(
                "📱 <b>کد ارسال شد!</b>\n\n"
                "🔷 <b>مرحله ۴ از ۶ — کد تایید</b>\n\nبفرستید:",
                parse_mode="HTML",
            )
            return CODE

        except FloodWaitError as e:
            await msg.edit_text(f"⏳ {e.seconds} ثانیه صبر کنید.")
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except PhoneNumberInvalidError:
            await msg.edit_text("❌ شماره نامعتبر.")
            return PHONE
        except ApiIdInvalidError:
            await msg.edit_text("❌ API نامعتبر.")
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"[PHONE] error: {e}")
            await msg.edit_text(f"❌ خطا: {e}")
            self.temp.pop(uid, None)
            return ConversationHandler.END

    async def rx_code(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        code = update.message.text.strip().replace(" ", "")
        data = self.temp[uid]
        logger.info(f"[CODE] user={uid}")

        msg = await update.message.reply_text("⏳ تایید...")

        try:
            await data["client"].sign_in(data["phone"], code)

            await msg.edit_text(
                "🔷 <b>مرحله ۵ از ۶ — پیشوند</b>\n\n"
                "یکی بفرست: <code>.</code> یا <code>!</code> یا <code>#</code>",
                parse_mode="HTML",
            )
            return PREFIX_STEP

        except SessionPasswordNeededError:
            await msg.edit_text(
                "🔐 <b>رمز دو مرحله‌ای:</b>\n\nبفرستید:",
                parse_mode="HTML",
            )
            return TWO_FA
        except PhoneCodeInvalidError:
            await msg.edit_text("❌ کد نامعتبر. دوباره:")
            return CODE
        except PhoneCodeExpiredError:
            await msg.edit_text("❌ کد منقضی شد. /start")
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"[CODE] error: {e}")
            await msg.edit_text(f"❌ خطا: {e}")
            self.temp.pop(uid, None)
            return ConversationHandler.END

    async def rx_2fa(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        pw = update.message.text.strip()
        data = self.temp[uid]
        logger.info(f"[2FA] user={uid}")

        msg = await update.message.reply_text("⏳ تایید...")

        try:
            await data["client"].sign_in(password=pw)
            await msg.edit_text(
                "🔷 <b>مرحله ۵ از ۶ — پیشوند</b>\n\n"
                "یکی: <code>.</code> یا <code>!</code> یا <code>#</code>",
                parse_mode="HTML",
            )
            return PREFIX_STEP
        except Exception as e:
            await msg.edit_text(f"❌ رمز نامعتبر: {e}")
            return TWO_FA

    async def rx_prefix(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = update.message.text.strip()
        prefix = text if text in [".", "!", "#", "/", "-", "~"] else "."
        data = self.temp[uid]
        logger.info(f"[PREFIX] user={uid} prefix={prefix}")

        msg = await update.message.reply_text(
            "⏳ نصب CipherElite...\n\nلطفاً صبر کنید...",
        )

        try:
            # Generate session string from file session
            session_str = StringSession.save(data["client"].session)
            session_str = fix_base64(session_str)
            await data["client"].disconnect()

            logger.info(
                f"[SESSION] user={uid} length={len(session_str)}"
            )

            # Save to database
            self.db.save_user(
                uid, data["api_id"], data["api_hash"],
                data["phone"], session_str, prefix,
            )

            # Start CipherElite
            logger.info(f"[INSTALL] Starting CipherElite for {uid}")
            ok = await self.manager.start_instance(
                uid, data["api_id"], data["api_hash"],
                session_str, prefix,
            )

            self.temp.pop(uid, None)

            if ok:
                await msg.edit_text(
                    f"✅ <b>CipherElite نصب شد!</b>\n\n"
                    f"پیشوند: <code>{prefix}</code>\n"
                    f"دستورات: <code>{prefix}help</code> "
                    f"<code>{prefix}ping</code>\n\n"
                    f"⚠️ مسئولیت با شماست.",
                    parse_mode="HTML",
                )
            else:
                await msg.edit_text(
                    "❌ خطا در نصب. دوباره /start"
                )
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"[PREFIX] error: {e}")
            self.temp.pop(uid, None)
            await msg.edit_text(f"❌ خطا: {e}")
            return ConversationHandler.END

    async def cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        logger.info(f"[CANCEL] user={uid}")
        data = self.temp.pop(uid, {})
        if "client" in data:
            try:
                await data["client"].disconnect()
            except Exception:
                pass
        await update.message.reply_text("❌ لغو شد.")
        return ConversationHandler.END

    # ── Register ─────────────────────────────────────────────

    def setup(self, app: Application):
        conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    self.setup_entry, pattern="^setup$"
                )
            ],
            states={
                API_ID: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.rx_api_id
                    )
                ],
                API_HASH: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.rx_api_hash
                    )
                ],
                PHONE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.rx_phone
                    )
                ],
                CODE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.rx_code
                    )
                ],
                TWO_FA: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.rx_2fa
                    )
                ],
                PREFIX_STEP: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.rx_prefix
                    )
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel),
            ],
            per_user=True,
            per_chat=True,
            per_message=False,
        )

        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(conv)
        app.add_handler(CallbackQueryHandler(
            self.btn_status, pattern="^status$"
        ))
        app.add_handler(CallbackQueryHandler(
            self.btn_stop, pattern="^stop$"
        ))
        app.add_handler(CallbackQueryHandler(
            self.btn_restart, pattern="^restart$"
        ))
        app.add_handler(CallbackQueryHandler(
            self.btn_delete, pattern="^delete$"
        ))
        app.add_handler(CallbackQueryHandler(
            self.btn_confirm_delete, pattern="^confirm_delete$"
        ))
        app.add_handler(CallbackQueryHandler(
            self.btn_cancel_delete, pattern="^cancel_delete$"
        ))
        app.add_handler(CallbackQueryHandler(
            self.btn_help, pattern="^help$"
        ))

        logger.info("All handlers registered.")