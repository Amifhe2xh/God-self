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
        existing = self.db.get_user(uid)

        if existing and existing["is_active"] and self.manager.is_running(uid):
            status = "🟢 فعال و در حال اجرا"
        elif existing and existing["is_active"]:
            status = "🟡 ذخیره شده ولی متوقف"
        else:
            status = "🔴 غیرفعال"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🚀 نصب CipherElite",
                callback_data="setup"
            )],
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

    # ── Button handlers (outside conversation) ───────────────

    async def btn_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        user = self.db.get_user(uid)

        if user and user["is_active"]:
            running = self.manager.is_running(uid)
            status_icon = "🟢 در حال اجرا" if running else "🟡 متوقف"
            txt = (
                f"**📊 وضعیت CipherElite**\n\n"
                f"**شماره:** `+{user['phone']}`\n"
                f"**API ID:** `{user['api_id']}`\n"
                f"**پیشوند:** `{user['prefix']}`\n"
                f"**وضعیت:** {status_icon}\n"
                f"**PID:** `{user['process_pid']}`"
            )
        else:
            txt = "**📊 وضعیت**\n\n❌ CipherElite نصب نشده."

        await q.message.reply_text(txt, parse_mode="Markdown")

    async def btn_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        await self.manager.stop_instance(uid)
        self.db.deactivate_user(uid)
        await q.message.reply_text(
            "**⏹ CipherElite متوقف شد.**", parse_mode="Markdown"
        )

    async def btn_restart(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        user = self.db.get_user(uid)

        if not user:
            return await q.message.reply_text(
                "**❌ ابتدا CipherElite را نصب کنید.**",
                parse_mode="Markdown",
            )

        msg = await q.message.reply_text(
            "**🔄 در حال ری‌استارت...**", parse_mode="Markdown"
        )

        ok = await self.manager.start_instance(
            uid, user["api_id"], user["api_hash"],
            user["session_string"], user.get("prefix", "."),
        )

        if ok:
            await msg.edit_text("**✅ CipherElite ری‌استارت شد.**")
        else:
            await msg.edit_text("**❌ خطا در ری‌استارت.**")

    async def btn_delete(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        await self.manager.stop_instance(uid)
        self.db.deactivate_user(uid)

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ بله، حذف کن", callback_data="confirm_delete"),
                InlineKeyboardButton("❌ نه", callback_data="cancel_delete"),
            ]
        ])
        await q.message.reply_text(
            "**⚠️ آیا مطمئنید؟**\n\n"
            "سشن شما حذف و CipherElite متوقف می‌شود.\n"
            "برای نصب مجدد باید دوباره وارد شوید.",
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
            "**🗑 حذف شد.** برای نصب مجدد /start بزنید.",
            parse_mode="Markdown",
        )

    async def btn_cancel_delete(self, update, ctx):
        q = update.callback_query
        await q.answer("لغو شد")
        await q.message.reply_text("**✅ لغو شد.**", parse_mode="Markdown")

    async def btn_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        await q.message.reply_text(
            "**📚 راهنمای نصب CipherElite**\n\n"
            "**قدم ۱:** از [my.telegram.org](https://my.telegram.org) "
            "API_ID و API_HASH بگیرید\n\n"
            "**قدم ۲:** روی «نصب CipherElite» بزنید\n\n"
            "**قدم ۳:** اطلاعات را وارد کنید:\n"
            "  • API_ID\n"
            "  • API_HASH\n"
            "  • شماره تلفن\n"
            "  • کد تایید\n"
            "  • رمز دو مرحله‌ای (اختیاری)\n"
            "  • پیشوند دستورات\n\n"
            "**قدم ۴:** CipherElite خودکار نصب می‌شود!\n\n"
            "**دستورات پیشفرض سلف:**\n"
            "`.help` `.ping` `.alive`\n"
            "`.اوقات` `.eval` `.terminal`\n"
            "و ۶۰+ پلاگین دیگر...",
            parse_mode="Markdown",
        )

    # ── Conversation: setup flow ─────────────────────────────

    async def setup_entry(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        self.temp.pop(uid, None)

        # Check if already running
        if self.manager.is_running(uid):
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔄 ری‌استارت",
                    callback_data="restart"
                )],
                [InlineKeyboardButton(
                    "⏹ توقف و نصب مجدد",
                    callback_data="confirm_reinstall"
                )],
            ])
            await q.message.reply_text(
                "**⚠️ CipherElite از قبل فعال است!**",
                reply_markup=kb,
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        await q.message.reply_text(
            "**🔷 نصب CipherElite — مرحله ۱/۶**\n\n"
            "**API_ID** خود را وارد کنید:\n\n"
            "از [my.telegram.org](https://my.telegram.org) → "
            "API development tools بگیرید.\n\n"
            " /cancel برای لغو",
            parse_mode="Markdown",
        )
        return API_ID

    async def rx_api_id(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            api_id = int(update.message.text.strip())
        except ValueError:
            await update.message.reply_text(
                "**❌ لطفاً یک عدد صحیح وارد کنید.**",
                parse_mode="Markdown",
            )
            return API_ID

        self.temp[update.effective_user.id] = {"api_id": api_id}
        await update.message.reply_text(
            "**🔷 مرحله ۲/۶ — API_HASH**\n\n"
            "API_HASH خود را وارد کنید:",
            parse_mode="Markdown",
        )
        return API_HASH

    async def rx_api_hash(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        h = update.message.text.strip()
        if len(h) < 20:
            await update.message.reply_text(
                "**❌ API_HASH نامعتبر است.**", parse_mode="Markdown"
            )
            return API_HASH

        self.temp[update.effective_user.id]["api_hash"] = h
        await update.message.reply_text(
            "**🔷 مرحله ۳/۶ — شماره تلفن**\n\n"
            "شماره خود را با فرمت بین‌المللی وارد کنید:\n"
            "مثال: `+989123456789`",
            parse_mode="Markdown",
        )
        return PHONE

    async def rx_phone(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        phone = update.message.text.strip().replace(" ", "")
        uid = update.effective_user.id
        data = self.temp[uid]

        msg = await update.message.reply_text(
            "**⏳ اتصال به تلگرام...**", parse_mode="Markdown"
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
                "**📱 کد تایید ارسال شد!**\n\n"
                "**🔷 مرحله ۴/۶ — کد تایید**\n\n"
                "کدی که از تلگرام دریافت کردید را وارد کنید:",
                parse_mode="Markdown",
            )
            return CODE

        except FloodWaitError as e:
            await msg.edit_text(
                f"**⏳ {e.seconds} ثانیه صبر کنید.**",
                parse_mode="Markdown",
            )
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except PhoneNumberInvalidError:
            await msg.edit_text("**❌ شماره نامعتبر.**", parse_mode="Markdown")
            return PHONE
        except ApiIdInvalidError:
            await msg.edit_text(
                "**❌ API_ID یا API_HASH نامعتبر.**",
                parse_mode="Markdown",
            )
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"connect error: {e}")
            await msg.edit_text(f"**❌ خطا:** `{e}`", parse_mode="Markdown")
            self.temp.pop(uid, None)
            return ConversationHandler.END

    async def rx_code(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        code = update.message.text.strip().replace(" ", "")
        uid = update.effective_user.id
        data = self.temp[uid]

        msg = await update.message.reply_text(
            "**⏳ تایید کد...**", parse_mode="Markdown"
        )

        try:
            await data["client"].sign_in(data["phone"], code)
            await msg.edit_text(
                "**🔷 مرحله ۵/۶ — پیشوند دستورات**\n\n"
                "پیشوند دستورات سلف را انتخاب کنید:\n\n"
                "مثال: `.` یا `!` یا `#`\n\n"
                "پیشوند پیشفرض: `.`",
                parse_mode="Markdown",
            )
            return PREFIX_STEP

        except SessionPasswordNeededError:
            await msg.edit_text(
                "**🔐 رمز دو مرحله‌ای فعال است.**\n\n"
                "رمز عبور خود را وارد کنید:",
                parse_mode="Markdown",
            )
            return TWO_FA
        except PhoneCodeInvalidError:
            await msg.edit_text(
                "**❌ کد نامعتبر. دوباره وارد کنید:**",
                parse_mode="Markdown",
            )
            return CODE
        except PhoneCodeExpiredError:
            await msg.edit_text(
                "**❌ کد منقضی شد. از /start شروع کنید.**",
                parse_mode="Markdown",
            )
            self.temp.pop(uid, None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"sign_in error: {e}")
            await msg.edit_text(f"**❌ خطا:** `{e}`", parse_mode="Markdown")
            self.temp.pop(uid, None)
            return ConversationHandler.END

    async def rx_2fa(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        pw = update.message.text.strip()
        uid = update.effective_user.id
        data = self.temp[uid]

        msg = await update.message.reply_text(
            "**⏳ تایید رمز...**", parse_mode="Markdown"
        )

        try:
            await data["client"].sign_in(password=pw)
            await msg.edit_text(
                "**🔷 مرحله ۵/۶ — پیشوند دستورات**\n\n"
                "پیشوند دستورات سلف را انتخاب کنید:\n\n"
                "مثال: `.` یا `!` یا `#`\n\n"
                "پیشوند پیشفرض: `.`",
                parse_mode="Markdown",
            )
            return PREFIX_STEP
        except Exception as e:
            await msg.edit_text(
                f"**❌ رمز نامعتبر:** `{e}`", parse_mode="Markdown"
            )
            return TWO_FA

    async def rx_prefix(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        prefix = text if text in [".", "!", "#", "/", "-", "~"] else "."
        uid = update.effective_user.id
        data = self.temp[uid]

        msg = await update.message.reply_text(
            "**⏳ در حال نصب CipherElite...\n\n"
            "🔷 مرحله ۶/۶ — راه‌اندازی**\n\n"
            "لطفاً صبر کنید...",
            parse_mode="Markdown",
        )

        try:
            # Get session string
            session_str = StringSession.save(data["client"].session)
            await data["client"].disconnect()

            # Save to database
            self.db.save_user(
                uid, data["api_id"], data["api_hash"],
                data["phone"], session_str, prefix,
            )

            # Start CipherElite
            ok = await self.manager.start_instance(
                uid, data["api_id"], data["api_hash"],
                session_str, prefix,
            )

            self.temp.pop(uid, None)

            if ok:
                await msg.edit_text(
                    "**✅ CipherElite با موفقیت نصب و فعال شد!**\n\n"
                    "🔷 **اطلاعات:**\n"
                    f"• پیشوند: `{prefix}`\n"
                    f"• شماره: `+{data['phone']}`\n\n"
                    "📖 **دستورات اصلی:**\n"
                    f"`{prefix}help` — راهنمای کامل\n"
                    f"`{prefix}ping` — تست سرعت\n"
                    f"`{prefix}alive` — وضعیت سلف\n\n"
                    "🧠 **ویژگی‌های فعال:**\n"
                    "• ۶۰+ پلاگین رسمی\n"
                    "• هوش مصنوعی داخلی\n"
                    "• ری‌استارت خودکار\n\n"
                    "⚠️ مسئولیت استفاده بر عهده شماست.",
                    parse_mode="Markdown",
                )
            else:
                await msg.edit_text(
                    "**❌ خطا در نصب CipherElite.**\n\n"
                    "لطفاً دوباره تلاش کنید: /start",
                    parse_mode="Markdown",
                )

            return ConversationHandler.END

        except Exception as e:
            logger.error(f"finish error: {e}")
            self.temp.pop(uid, None)
            await msg.edit_text(
                f"**❌ خطا:** `{e}`\n\n/start برای تلاش مجدد",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

    async def cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        data = self.temp.pop(uid, {})
        if "client" in data:
            try:
                await data["client"].disconnect()
            except Exception:
                pass
        await update.message.reply_text(
            "**❌ لغو شد.**", parse_mode="Markdown"
        )
        return ConversationHandler.END

    # ── Register everything ──────────────────────────────────

    def setup(self, app: Application):
        conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.setup_entry, pattern="^setup$")
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
        )

        # Command handlers
        app.add_handler(CommandHandler("start", self.cmd_start))

        # Conversation
        app.add_handler(conv)

        # Button handlers
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