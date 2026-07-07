import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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

logger = logging.getLogger(__name__)

(
    API_ID,
    API_HASH,
    PHONE,
    CODE,
    TWO_FA,
    PREFIX_STEP,
) = range(6)


class BotHandlers:
    def __init__(self, db: Database, manager: CipherManager):
        self.db = db
        self.manager = manager
        self.temp: dict[int, dict] = {}

    # ── /start ───────────────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        logger.info(f"[/start] user={uid}")
        existing = self.db.get_user(uid)

        if existing and existing["is_active"] and self.manager.is_running(uid):
            status = "🟢 فعال و در حال اجرا"
        elif existing and existing["is_active"]:
            status = "🟡 ذخیره شده ولی متوقف"
        else:
            status = "🔴 غیرفعال"

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

        await update.message.reply_text(
            f"**🔷 CipherElite Deployer Bot**\n\n"
            f"سلام **{update.effective_user.first_name}**!\n\n"
            f"این ربات سلف‌بات **CipherElite** رو روی اکانت "
            f"تلگرام شما نصب و مدیریت می‌کنه.\n\n"
            f"**📊 وضعیت شما:** {status}\n\n"
            f"**🧠 ویژگی‌ها:**\n"
            f"• هوش مصنوعی داخلی\n"
            f"• ۶۰+ پلاگین رسمی\n"
            f"• امنیت بالا با رمزنگاری سشن\n"
            f"• ری‌استارت خودکار\n\n"
            f"⚠️ **مسئولیت استفاده بر عهده شماست.**",
            reply_markup=kb,
            parse_mode="Markdown",
        )

    # ── button handlers outside conversation ─────────────────

    async def btn_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        logger.info(f"[btn_status] user={uid}")
        user = self.db.get_user(uid)

        if user and user["is_active"]:
            running = self.manager.is_running(uid)
            icon = "🟢 در حال اجرا" if running else "🟡 متوقف"
            txt = (
                f"**📊 وضعیت CipherElite**\n\n"
                f"**شماره:** `+{user['phone']}`\n"
                f"**API ID:** `{user['api_id']}`\n"
                f"**پیشوند:** `{user['prefix']}`\n"
                f"**وضعیت:** {icon}\n"
                f"**PID:** `{user['process_pid']}`"
            )
        else:
            txt = "**📊 وضعیت**\n\n❌ CipherElite نصب نشده."

        await q.message.reply_text(txt, parse_mode="Markdown")

    async def btn_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        logger.info(f"[btn_stop] user={uid}")
        await self.manager.stop_instance(uid)
        self.db.deactivate_user(uid)
        await q.message.reply_text(
            "**⏹ CipherElite متوقف شد.**", parse_mode="Markdown"
        )

    async def btn_restart(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        logger.info(f"[btn_restart] user={uid}")
        user = self.db.get_user(uid)

        if not user:
            return await q.message.reply_text(
                "**❌ ابتدا نصب کنید.**", parse_mode="Markdown"
            )

        msg = await q.message.reply_text(
            "**🔄 ری‌استارت...**", parse_mode="Markdown"
        )

        ok = await self.manager.start_instance(
            uid, user["api_id"], user["api_hash"],
            user["session_string"], user.get("prefix", "."),
        )
        await msg.edit_text(
            "**✅ ری‌استارت شد.**" if ok else "**❌ خطا در ری‌استارت.**"
        )

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
        await q.message.reply_text(
            "**⚠️ حذف شود؟**\nسشن شما حذف و CipherElite متوقف می‌شود.",
            reply_markup=kb,
            parse_mode="Markdown",
        )

    async def btn_confirm_delete(self, update, ctx):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        with self.db._conn() as conn:
            conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
        await q.message.reply_text(
            "**🗑 حذف شد.** /start برای نصب مجدد.",
            parse_mode="Markdown",
        )

    async def btn_cancel_delete(self, update, ctx):
        q = update.callback_query
        await q.answer()
        await q.message.reply_text("**✅ لغو شد.**", parse_mode="Markdown")

    async def btn_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        await q.message.reply_text(
            "**📚 راهنما**\n\n"
            "۱. از my.telegram.org API بگیرید\n"
            "۲. نصب CipherElite بزنید\n"
            "۳. اطلاعات را وارد کنید\n"
            "۴. تمام!\n\n"
            "دستورات سلف:\n"
            "`.help` `.ping` `.alive`",
            parse_mode="Markdown",
        )

    # ── setup: separate entry handler ────────────────────────

    async def setup_clicked(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """This is the entry point — always answer the callback first."""
        q = update.callback_query
        uid = q.from_user.id
        logger.info(f"[setup_clicked] user={uid}")

        try:
            await q.answer("در حال آماده‌سازی...")
        except Exception as e:
            logger.warning(f"answer failed: {e}")

        # check if already running
        if self.manager.is_running(uid):
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 ری‌استارت", callback_data="restart")],
            ])
            await q.message.reply_text(
                "**⚠️ CipherElite از قبل فعال است!**",
                reply_markup=kb,
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        await q.message.reply_text(
            "**🔷 مرحله ۱/۶ — API_ID**\n\n"
            "از my.telegram.org بگیرید و بفرستید.\n\n"
            "/cancel = لغو",
            parse_mode="Markdown",
        )
        logger.info(f"[setup_clicked] -> API_ID state for user={uid}")
        return API_ID

    # ── conversation steps ───────────────────────────────────

    async def rx_api_id(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = update.message.text.strip()
        logger.info(f"[rx_api_id] user={uid} text={text}")

        try:
            api_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "**❌ عدد صحیح وارد کنید.**", parse_mode="Markdown"
            )
            return API_ID

        self.temp[uid] = {"api_id": api_id}
        await update.message.reply_text(
            "**🔷 مرحله ۲/۶ — API_HASH**\n\nبفرستید:",
            parse_mode="Markdown",
        )
        return API_HASH

    async def rx_api_hash(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        h = update.message.text.strip()
        logger.info(f"[rx_api_hash] user={uid}")

        if len(h) < 20:
            await update.message.reply_text(
                "**❌ نامعتبر.**", parse_mode="Markdown"
            )
            return API_HASH

        self.temp[uid]["api_hash"] = h
        await update.message.reply_text(
            "**🔷 مرحله ۳/۶ — شماره تلفن**\n\n"
            "مثال: `+989123456789`",
            parse_mode="Markdown",
        )
        return PHONE

    async def rx_phone(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        phone = update.message.text.strip().replace(" ", "")
        data = self.temp[uid]
        logger.info(f"[rx_phone] user={uid} phone={phone}")

        msg = await update.message.reply_text(
            "**⏳ اتصال...**", parse_mode="Markdown"
        )

        try:
            client = TelegramClient(
                StringSession(), data["api_id"], data["api_hash"],
                connection_retries=5, retry_delay=1,
            )
            await client.connect()
            await client.send_code_request(phone)
            data["phone"] = phone
            data["client"] = client

            await msg.edit_text(
                "**📱 کد ارسال شد!\n\n"
                "🔷 مرحله ۴/۶ — کد تایید**\n\nبفرستید:",
                parse_mode="Markdown",
            )
            return CODE

        except FloodWaitError as e:
            await msg.edit_text(f"**⏳ {e.seconds} ثانیه صبر کنید.**")
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except PhoneNumberInvalidError:
            await msg.edit_text("**❌ شماره نامعتبر.**")
            return PHONE
        except ApiIdInvalidError:
            await msg.edit_text("**❌ API نامعتبر.**")
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"[rx_phone] error: {e}")
            await msg.edit_text(f"**❌ خطا:** `{e}`")
            self.temp.pop(uid, None)
            return ConversationHandler.END

    async def rx_code(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        code = update.message.text.strip().replace(" ", "")
        data = self.temp[uid]
        logger.info(f"[rx_code] user={uid}")

        msg = await update.message.reply_text("**⏳ تایید...**")

        try:
            await data["client"].sign_in(data["phone"], code)
            await msg.edit_text(
                "**🔷 مرحله ۵/۶ — پیشوند**\n\n"
                "یکی بفرست: `.` یا `!` یا `#`",
                parse_mode="Markdown",
            )
            return PREFIX_STEP

        except SessionPasswordNeededError:
            await msg.edit_text(
                "**🔐 رمز دو مرحله‌ای:**\n\nرمز بفرستید:",
                parse_mode="Markdown",
            )
            return TWO_FA
        except PhoneCodeInvalidError:
            await msg.edit_text("**❌ کد نامعتبر. دوباره:**")
            return CODE
        except PhoneCodeExpiredError:
            await msg.edit_text("**❌ کد منقضی شد. /start**")
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"[rx_code] error: {e}")
            await msg.edit_text(f"**❌ خطا:** `{e}`")
            self.temp.pop(uid, None)
            return ConversationHandler.END

    async def rx_2fa(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        pw = update.message.text.strip()
        data = self.temp[uid]
        logger.info(f"[rx_2fa] user={uid}")

        msg = await update.message.reply_text("**⏳ تایید...**")

        try:
            await data["client"].sign_in(password=pw)
            await msg.edit_text(
                "**🔷 مرحله ۵/۶ — پیشوند**\n\n"
                "یکی بفرست: `.` یا `!` یا `#`",
                parse_mode="Markdown",
            )
            return PREFIX_STEP
        except Exception as e:
            await msg.edit_text(f"**❌ رمز نامعتبر:** `{e}`")
            return TWO_FA

    async def rx_prefix(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = update.message.text.strip()
        prefix = text if text in [".", "!", "#", "/", "-", "~"] else "."
        data = self.temp[uid]
        logger.info(f"[rx_prefix] user={uid} prefix={prefix}")

        msg = await update.message.reply_text(
            "**⏳ نصب CipherElite...\n\n"
            "🔷 مرحله ۶/۶ — راه‌اندازی**",
            parse_mode="Markdown",
        )

        try:
            session_str = StringSession.save(data["client"].session)
            await data["client"].disconnect()

            self.db.save_user(
                uid, data["api_id"], data["api_hash"],
                data["phone"], session_str, prefix,
            )

            ok = await self.manager.start_instance(
                uid, data["api_id"], data["api_hash"],
                session_str, prefix,
            )

            self.temp.pop(uid, None)

            if ok:
                await msg.edit_text(
                    f"**✅ CipherElite نصب شد!**\n\n"
                    f"پیشوند: `{prefix}`\n"
                    f"دستورات: `{prefix}help` `{prefix}ping`\n\n"
                    f"⚠️ مسئولیت با شماست.",
                    parse_mode="Markdown",
                )
            else:
                await msg.edit_text(
                    "**❌ خطا. دوباره /start**",
                    parse_mode="Markdown",
                )
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"[rx_prefix] error: {e}")
            self.temp.pop(uid, None)
            await msg.edit_text(f"**❌ خطا:** `{e}`")
            return ConversationHandler.END

    async def cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        logger.info(f"[cancel] user={uid}")
        data = self.temp.pop(uid, {})
        if "client" in data:
            try:
                await data["client"].disconnect()
            except Exception:
                pass
        await update.message.reply_text("**❌ لغو شد.**", parse_mode="Markdown")
        return ConversationHandler.END

    # ── fallback: handle orphan callback queries ─────────────

    async def fallback_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Catch any callback_query not handled above."""
        q = update.callback_query
        logger.warning(f"[fallback_callback] data={q.data} user={q.from_user.id}")
        await q.answer("خطا — لطفاً /start بزنید")

    # ── Register everything ──────────────────────────────────

    def setup(self, app: Application):

        # ── ConversationHandler ──
        conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    self.setup_clicked,
                    pattern="^setup$",
                )
            ],
            states={
                API_ID: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.rx_api_id)
                ],
                API_HASH: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.rx_api_hash)
                ],
                PHONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.rx_phone)
                ],
                CODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.rx_code)
                ],
                TWO_FA: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.rx_2fa)
                ],
                PREFIX_STEP: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.rx_prefix)
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel),
            ],
            per_user=True,
            per_chat=True,
            per_message=False,
        )

        # Order matters: most specific first
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(conv)

        # Standalone button handlers (AFTER conversation)
        app.add_handler(CallbackQueryHandler(self.btn_status, pattern="^status$"))
        app.add_handler(CallbackQueryHandler(self.btn_stop, pattern="^stop$"))
        app.add_handler(CallbackQueryHandler(self.btn_restart, pattern="^restart$"))
        app.add_handler(CallbackQueryHandler(self.btn_delete, pattern="^delete$"))
        app.add_handler(CallbackQueryHandler(self.btn_confirm_delete, pattern="^confirm_delete$"))
        app.add_handler(CallbackQueryHandler(self.btn_cancel_delete, pattern="^cancel_delete$"))
        app.add_handler(CallbackQueryHandler(self.btn_help, pattern="^help$"))

        # Fallback for unhandled callbacks
        app.add_handler(CallbackQueryHandler(self.fallback_callback))

        logger.info("All handlers registered.")