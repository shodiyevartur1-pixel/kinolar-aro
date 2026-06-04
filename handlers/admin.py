import logging
import asyncio
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, Forbidden, BadRequest

from config import ADMIN_IDS, BOT_USERNAME
from utils.db import (
    get_movies,
    get_movie,
    save_movie,
    save_series,
    add_series_part,
    delete_movie,
    get_channels,
    add_channel,
    remove_channel,
    get_stats,
)

logger = logging.getLogger(__name__)

# ─── ConversationHandler holatlari ───────────────────────
WAIT_CODE, WAIT_CAPTION, WAIT_FILE = range(3)
WAIT_CH_ID, WAIT_CH_TITLE, WAIT_CH_LINK = range(10, 13)
WAIT_DEL_CODE = 20
WAIT_BROADCAST = 30
WAIT_SER_CODE, WAIT_SER_CAPTION, WAIT_SER_PARTS = range(40, 43)


# ─── Yordamchi funksiyalar ────────────────────────────────
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or not is_admin(user.id):
            try:
                if update.message:
                    await update.message.reply_text("❌ Ruxsat yo'q.")
                elif update.callback_query:
                    await update.callback_query.answer("❌ Ruxsat yo'q.", show_alert=True)
            except TelegramError as e:
                logger.warning("admin_only xabar yuborishda xato: %s", e)
            return ConversationHandler.END
        return await func(update, ctx)
    return wrapper


def escape_md(text: str) -> str:
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{ch}" if ch in special else ch for ch in str(text))


async def _reply_or_send(update: Update, text: str, parse_mode=None):
    """message yoki callback_query orqali xabar yuboradi."""
    if update.message:
        await update.message.reply_text(text, parse_mode=parse_mode)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode=parse_mode)


async def safe_edit(q, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN_V2):
    try:
        await q.message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error("safe_edit BadRequest: %s", e)
    except TelegramError as e:
        logger.error("safe_edit xatosi: %s", e)


def _movie_preview(code: str, caption: str, downloads: int = 0) -> str:
    """Foydalanuvchiga ko'rinadigan caption preview."""
    return (
        f"*🎬 \\#{escape_md(code)}*\n\n"
        f"*‣ Film nomi: {escape_md(caption)}*\n\n"
        f"*🗂 Yuklash: {downloads}*\n\n"
        f"*🤖 Bizning bot: @{escape_md(BOT_USERNAME)}*"
    )


# ─── Admin panel menyusi ──────────────────────────────────
def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Kino qo'shish",    callback_data="adm_add"),
            InlineKeyboardButton("🗑 Kino o'chirish",    callback_data="adm_del"),
        ],
        [
            InlineKeyboardButton("📋 Kinolar ro'yxati",  callback_data="adm_list"),
            InlineKeyboardButton("📊 Statistika",        callback_data="adm_stats"),
        ],
        [
            InlineKeyboardButton("📢 Kanal qo'shish",   callback_data="adm_ch_add"),
            InlineKeyboardButton("🚫 Kanal o'chirish",   callback_data="adm_ch_del"),
        ],
        [
            InlineKeyboardButton("📋 Kanallar ro'yxati", callback_data="adm_ch_list"),
            InlineKeyboardButton("📣 Broadcast",         callback_data="adm_broadcast"),
            InlineKeyboardButton("📺 Serial qo'shish",   callback_data="adm_series"),
        ],
    ])


def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back")
    ]])


def _admin_panel_text() -> str:
    try:
        movies   = get_movies()
        channels = get_channels()
        stats    = get_stats()
        # Jami yuklanishlar
        total_dl = sum(m.get("downloads", 0) for m in movies.values())
        return (
            f"🛠 *Admin panel*\n\n"
            f"🎬 Kinolar: `{len(movies)}`\n"
            f"📢 Kanallar: `{len(channels)}`\n"
            f"👥 Foydalanuvchilar: `{len(stats.get('users', {}))}`\n"
            f"📥 So'rovlar: `{stats.get('requests', 0)}`\n"
            f"⬇️ Jami yuklanishlar: `{total_dl}`"
        )
    except Exception as e:
        logger.error("_admin_panel_text xatosi: %s", e)
        return "🛠 *Admin panel*\n\n⚠️ Ma'lumot yuklanmadi\\."


@admin_only
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(
            _admin_panel_text(),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=admin_menu_keyboard(),
        )
    except TelegramError as e:
        logger.error("admin_panel xatosi: %s", e)


# ─── Callback router ──────────────────────────────────────
async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    data = q.data
    logger.info("Admin callback: user=%s data=%s", q.from_user.id, data)

    simple_handlers = {
        "adm_list":    _cb_show_movie_list,
        "adm_stats":   _cb_show_stats,
        "adm_ch_list": _cb_show_channels,
        "adm_ch_del":  _cb_show_ch_del_list,
        "adm_back":    _cb_back_to_menu,
    }

    if data in simple_handlers:
        await simple_handlers[data](q, ctx)
    elif data.startswith("confirm_del_"):
        await _cb_confirm_delete(q, ctx)
    elif data == "cancel_del":
        await safe_edit(q, "❌ Bekor qilindi\\.")
    elif data.startswith("ch_del_"):
        await _cb_delete_channel(q, ctx)
    elif data == "adm_broadcast":
        await _cb_broadcast_start(q, ctx)
    elif data == "adm_series":
        await _cb_series_start(q, ctx)


async def _cb_back_to_menu(q, ctx):
    await safe_edit(q, _admin_panel_text(), reply_markup=admin_menu_keyboard())


async def _cb_show_movie_list(q, ctx):
    try:
        movies = get_movies()
    except Exception as e:
        logger.error("get_movies xatosi: %s", e)
        await safe_edit(q, "⚠️ Ma'lumotlar yuklanmadi\\.", reply_markup=back_button())
        return

    if not movies:
        await safe_edit(q, "📭 Hozircha kino yo'q\\.", reply_markup=back_button())
        return

    lines = [f"📋 *Kinolar — {escape_md(len(movies))} ta:*\n"]
    for i, (code, mv) in enumerate(sorted(movies.items()), 1):
        caption     = escape_md(mv.get("caption", "—"))
        downloads   = mv.get("downloads", 0)
        is_series   = mv.get("is_series", False)
        parts_count = len(mv.get("parts", []))
        extra       = f" \\({parts_count} qism\\)" if is_series else ""
        lines.append(f"{escape_md(i)}\\. `{escape_md(code)}` \\- {caption}{extra}")

    text = "\n\n".join(lines)
    if len(text) > 4000:
        text = text[:3980] + "\n\\.\\.\\."

    await safe_edit(q, text, reply_markup=back_button())


async def _cb_show_stats(q, ctx):
    try:
        stats    = get_stats()
        movies   = get_movies()
        channels = get_channels()
    except Exception as e:
        logger.error("stats xatosi: %s", e)
        await safe_edit(q, "⚠️ Statistika yuklanmadi\\.", reply_markup=back_button())
        return

    total_dl = sum(m.get("downloads", 0) for m in movies.values())
    # Top 3 kino
    top = sorted(movies.values(), key=lambda m: m.get("downloads", 0), reverse=True)[:3]
    top_lines = []
    for i, m in enumerate(top, 1):
        top_lines.append(
            f"  {i}\\. `{escape_md(m['code'])}` — {escape_md(m.get('caption','?'))} \\({m.get('downloads',0)}\\)"
        )

    text = (
        f"📊 *Statistika*\n\n"
        f"👥 Foydalanuvchilar: `{len(stats.get('users', {}))}`\n"
        f"📥 Jami so'rovlar: `{stats.get('requests', 0)}`\n"
        f"🎬 Kinolar soni: `{len(movies)}`\n"
        f"⬇️ Jami yuklanishlar: `{total_dl}`\n"
        f"📢 Kanallar: `{len(channels)}`\n\n"
        f"🏆 *Top kinolar:*\n" + "\n".join(top_lines if top_lines else ["  _Hozircha yo'q_"])
    )
    await safe_edit(q, text, reply_markup=back_button())


async def _cb_show_channels(q, ctx):
    try:
        channels = get_channels()
    except Exception as e:
        logger.error("get_channels xatosi: %s", e)
        await safe_edit(q, "⚠️ Kanallar yuklanmadi\\.", reply_markup=back_button())
        return

    if not channels:
        text = "📢 *Majburiy kanallar:*\n\n_Hozircha yo'q_"
    else:
        lines = ["📢 *Majburiy kanallar:*\n"]
        for ch in channels.values():
            title = escape_md(ch.get("title", "?"))
            ch_id = escape_md(ch.get("id", "?"))
            lines.append(f"• {title} — `{ch_id}`")
        text = "\n".join(lines)

    await safe_edit(q, text, reply_markup=back_button())


async def _cb_show_ch_del_list(q, ctx):
    try:
        channels = get_channels()
    except Exception as e:
        logger.error("get_channels xatosi: %s", e)
        await safe_edit(q, "⚠️ Kanallar yuklanmadi\\.", reply_markup=back_button())
        return

    if not channels:
        await safe_edit(q, "📭 O'chiriladigan kanal yo'q\\.", reply_markup=back_button())
        return

    buttons = [
        [InlineKeyboardButton(f"🚫 {ch.get('title', ch_id)}", callback_data=f"ch_del_{ch_id}")]
        for ch_id, ch in channels.items()
    ]
    buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="adm_back")])
    await safe_edit(
        q, "Qaysi kanalni o'chirmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=None,
    )


async def _cb_confirm_delete(q, ctx):
    code = q.data.replace("confirm_del_", "").upper()
    try:
        success = delete_movie(code)
    except Exception as e:
        logger.error("delete_movie xatosi: %s", e)
        await safe_edit(q, "⚠️ O'chirishda xatolik yuz berdi\\.", reply_markup=back_button())
        return

    if success:
        await safe_edit(q, f"✅ `{escape_md(code)}` muvaffaqiyatli o'chirildi\\.")
    else:
        await safe_edit(q, f"❌ `{escape_md(code)}` topilmadi\\.")


async def _cb_delete_channel(q, ctx):
    ch_id = q.data.replace("ch_del_", "")
    try:
        channels = get_channels()
        title    = channels.get(ch_id, {}).get("title", ch_id)
        success  = remove_channel(ch_id)
    except Exception as e:
        logger.error("remove_channel xatosi: %s", e)
        await safe_edit(q, "⚠️ O'chirishda xatolik\\.", reply_markup=back_button())
        return

    if success:
        await safe_edit(q, f"✅ *{escape_md(title)}* o'chirildi\\.")
    else:
        await safe_edit(q, "❌ Kanal topilmadi\\.")


# ─── Kino qo'shish ────────────────────────────────────────
@admin_only
async def adm_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = (
        "🎬 *Kino qo'shish*\n\n"
        "1️⃣ Kino *kodini* yuboring\\.\n"
        "_Masalan:_ `VIDEO\\-2461`\n\n"
        "/bekor — bekor qilish"
    )
    try:
        if update.message:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await update.callback_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    except TelegramError as e:
        logger.error("adm_add_start xatosi: %s", e)
        return ConversationHandler.END
    return WAIT_CODE


async def adm_add_get_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()

    if len(code) < 1 or len(code) > 50:
        await update.message.reply_text(
            "⚠️ Kod 1\\-50 ta belgidan iborat bo'lishi kerak\\. Qayta kiriting:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WAIT_CODE

    try:
        existing = get_movie(code)
    except Exception as e:
        logger.error("get_movie xatosi: %s", e)
        await update.message.reply_text("⚠️ Xatolik yuz berdi. Qayta urinib ko'ring.")
        return WAIT_CODE

    if existing:
        await update.message.reply_text(
            f"⚠️ `{escape_md(code)}` kodi allaqachon mavjud\\. Boshqa kod kiriting:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WAIT_CODE

    ctx.user_data["new_code"] = code
    await update.message.reply_text(
        f"✅ Kod: `{escape_md(code)}`\n\n2️⃣ Kino *nomini* yuboring:",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return WAIT_CAPTION


async def adm_add_get_caption(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    caption = update.message.text.strip()
    if not caption:
        await update.message.reply_text("⚠️ Nom bo'sh bo'lmasin. Qayta kiriting:")
        return WAIT_CAPTION

    ctx.user_data["new_caption"] = caption
    await update.message.reply_text(
        f"✅ Nomi: *{escape_md(caption)}*\n\n3️⃣ Endi *video yoki faylni* yuboring:",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return WAIT_FILE


async def adm_add_get_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code    = ctx.user_data.get("new_code")
    caption = ctx.user_data.get("new_caption")

    if not code or not caption:
        await update.message.reply_text("⚠️ Jarayon buzildi. /add dan qayta boshlang.")
        ctx.user_data.clear()
        return ConversationHandler.END

    if update.message.video:
        file_id, file_type = update.message.video.file_id, "video"
    elif update.message.document:
        file_id, file_type = update.message.document.file_id, "document"
    else:
        await update.message.reply_text("❌ Faqat video yoki fayl yuboring.")
        return WAIT_FILE

    try:
        save_movie(code, file_id, caption, file_type)
    except Exception as e:
        logger.error("save_movie xatosi: %s", e)
        await update.message.reply_text("⚠️ Saqlashda xatolik yuz berdi. Qayta urinib ko'ring.")
        return WAIT_FILE

    share_url = f"https://t.me/{BOT_USERNAME}?start={code}"
    await update.message.reply_text(
        f"✅ *Saqlandi\\!*\n\n"
        f"🔗 Havola: `{escape_md(share_url)}`\n\n"
        f"📌 *Foydalanuvchiga ko'rinadigan caption:*\n\n"
        + _movie_preview(code, caption),
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ─── Kino o'chirish ───────────────────────────────────────
@admin_only
async def adm_del_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        movies = get_movies()
    except Exception as e:
        logger.error("get_movies xatosi: %s", e)
        await _reply_or_send(update, "⚠️ Xatolik yuz berdi.")
        return ConversationHandler.END

    if not movies:
        await _reply_or_send(update, "📭 O'chiriladigan kino yo'q.")
        return ConversationHandler.END

    await _reply_or_send(
        update,
        "🗑 *Qaysi kinoni o'chirmoqchisiz?*\n\n"
        "Kino kodini yuboring\\.\n\n"
        "/bekor — bekor qilish",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return WAIT_DEL_CODE


async def adm_del_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()

    try:
        movie = get_movie(code)
    except Exception as e:
        logger.error("get_movie xatosi: %s", e)
        await update.message.reply_text("⚠️ Xatolik yuz berdi. Qayta urinib ko'ring.")
        return WAIT_DEL_CODE

    if not movie:
        await update.message.reply_text(
            f"❌ `{escape_md(code)}` topilmadi\\. Boshqa kod kiriting:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WAIT_DEL_CODE

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha, o'chir", callback_data=f"confirm_del_{code}"),
        InlineKeyboardButton("❌ Bekor",      callback_data="cancel_del"),
    ]])
    await update.message.reply_text(
        f"⚠️ *{escape_md(movie.get('caption', code))}* "
        f"\\(`{escape_md(code)}`\\) o'chirilsinmi?",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )
    return ConversationHandler.END


# ─── Kanal qo'shish ───────────────────────────────────────
@admin_only
async def adm_ch_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = (
        "📢 *Kanal qo'shish*\n\n"
        "Kanal *ID* sini yuboring\\.\n"
        "_Masalan:_ `@KinolarAro` yoki `\\-1001234567890`\n\n"
        "⚠️ Avval botni kanalga *admin* qilib qo'shing\\!\n\n"
        "/bekor — bekor qilish"
    )
    try:
        if update.message:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await update.callback_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    except TelegramError as e:
        logger.error("adm_ch_add_start xatosi: %s", e)
        return ConversationHandler.END
    return WAIT_CH_ID


async def adm_ch_get_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ch_id = update.message.text.strip()

    if not (ch_id.startswith("@") or ch_id.startswith("-")):
        await update.message.reply_text(
            "⚠️ Noto'g'ri format\\. `@username` yoki `\\-100...` shaklida yuboring:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WAIT_CH_ID

    try:
        member = await ctx.bot.get_chat_member(chat_id=ch_id, user_id=ctx.bot.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text(
                "⚠️ Bot ushbu kanalda admin emas\\. Avval admin qilib, keyin qayta yuboring:",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return WAIT_CH_ID
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            "❌ Kanal topilmadi yoki bot a'zo emas\\. "
            "Botni kanalga qo'shib, admin bering, keyin qayta urinib ko'ring:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WAIT_CH_ID
    except TelegramError as e:
        logger.warning("Kanal tekshirishda xato: %s", e)

    ctx.user_data["new_ch_id"] = ch_id
    await update.message.reply_text(
        "✅ ID saqlandi\\.\n\nKanal *nomini* yuboring \\(ekranda ko'rinadigan\\):",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return WAIT_CH_TITLE


async def adm_ch_get_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("⚠️ Nom bo'sh bo'lmasin. Qayta kiriting:")
        return WAIT_CH_TITLE

    ctx.user_data["new_ch_title"] = title
    await update.message.reply_text(
        "✅ Nom saqlandi\\.\n\nKanal *havolasini* yuboring \\(`https://t\\.me/kanal`\\):",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return WAIT_CH_LINK


async def adm_ch_get_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    link  = update.message.text.strip()
    ch_id = ctx.user_data.get("new_ch_id")
    title = ctx.user_data.get("new_ch_title")

    if not ch_id or not title:
        await update.message.reply_text("⚠️ Jarayon buzildi. /addchannel dan qayta boshlang.")
        ctx.user_data.clear()
        return ConversationHandler.END

    if not link.startswith("http"):
        await update.message.reply_text(
            "⚠️ Havola `https://` bilan boshlanishi kerak\\. Qayta kiriting:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WAIT_CH_LINK

    try:
        add_channel(ch_id, title, link)
    except Exception as e:
        logger.error("add_channel xatosi: %s", e)
        await update.message.reply_text("⚠️ Saqlashda xatolik. Qayta urinib ko'ring.")
        return WAIT_CH_LINK

    await update.message.reply_text(
        f"✅ *{escape_md(title)}* kanali qo'shildi\\!\n"
        f"ID: `{escape_md(ch_id)}`\n"
        f"Havola: {escape_md(link)}",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ─── Broadcast ────────────────────────────────────────────
async def _cb_broadcast_start(q, ctx):
    """Inline tugma orqali broadcast: faqat yo'riqnoma yuboradi."""
    await q.answer()
    await q.message.reply_text(
        "📣 *Broadcast*\n\nHammaga yubormoqchi bo'lgan xabaringizni yuboring\\.\n\n/bekor — bekor qilish",
        parse_mode="MarkdownV2",
    )
    ctx.user_data["awaiting_broadcast"] = True


@admin_only
async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Faqat /broadcast buyrug'i orqali — inline rejim uchun alohida."""
    if not ctx.args:
        await update.message.reply_text(
            "📣 *Broadcast*\n\nXabar matnini keyingi satrda yoki shu yerda yuboring\\.\n"
            "Ishlatish: `/broadcast Xabar matni`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    text = " ".join(ctx.args)
    await _do_broadcast(update, ctx, text)


async def broadcast_get_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """ConversationHandler orqali broadcast matni qabul qilish."""
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("⚠️ Xabar bo'sh bo'lmasin. Qayta yuboring:")
        return WAIT_BROADCAST
    await _do_broadcast(update, ctx, text)
    return ConversationHandler.END


async def _do_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str):
    """Barcha foydalanuvchilarga async xabar yuborish."""
    try:
        stats = get_stats()
    except Exception as e:
        logger.error("get_stats xatosi: %s", e)
        await update.message.reply_text("⚠️ Foydalanuvchilar yuklanmadi.")
        return

    users = stats.get("users", {})
    total = len(users)

    if total == 0:
        await update.message.reply_text("📭 Foydalanuvchilar yo'q.")
        return

    progress_msg = await update.message.reply_text(f"📤 Yuborilmoqda... 0/{total}")
    sent = failed = 0

    for uid in list(users.keys()):
        try:
            await ctx.bot.send_message(chat_id=int(uid), text=text)
            sent += 1
        except Forbidden:
            failed += 1
        except TelegramError as e:
            logger.warning("broadcast uid=%s xato: %s", uid, e)
            failed += 1

        # Har 20 ta yuborilganda progress yangilanadi
        if (sent + failed) % 20 == 0:
            try:
                await progress_msg.edit_text(f"📤 Yuborilmoqda... {sent + failed}/{total}")
            except TelegramError:
                pass

        # Rate limit: har xabarda 35ms kutamiz
        await asyncio.sleep(0.035)

    try:
        await progress_msg.edit_text(
            f"✅ Broadcast tugadi\\!\n\n"
            f"📤 Yuborildi: `{sent}/{total}`\n"
            f"❌ Xatolik: `{failed}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except TelegramError as e:
        logger.error("broadcast natija xatosi: %s", e)


# ─── Bekor qilish ─────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# ─── ConversationHandler lar ──────────────────────────────
def add_movie_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("add", adm_add_start),
            CallbackQueryHandler(adm_add_start, pattern="^adm_add$"),
        ],
        states={
            WAIT_CODE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_get_code)],
            WAIT_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_get_caption)],
            WAIT_FILE:    [MessageHandler(filters.VIDEO | filters.Document.ALL, adm_add_get_file)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
        allow_reentry=True,
        per_message=False,
        conversation_timeout=300,
    )


def del_movie_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("delete", adm_del_start),
            CallbackQueryHandler(adm_del_start, pattern="^adm_del$"),
        ],
        states={
            WAIT_DEL_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_del_confirm)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
        allow_reentry=True,
        per_message=False,
        conversation_timeout=300,
    )


def add_channel_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("addchannel", adm_ch_add_start),
            CallbackQueryHandler(adm_ch_add_start, pattern="^adm_ch_add$"),
        ],
        states={
            WAIT_CH_ID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ch_get_id)],
            WAIT_CH_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ch_get_title)],
            WAIT_CH_LINK:  [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ch_get_link)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
        allow_reentry=True,
        per_message=False,
        conversation_timeout=300,
    )



# ─── Serial qo'shish ──────────────────────────────────────
async def _cb_series_start(q, ctx):
    ctx.user_data.clear()
    await q.message.reply_text(
        "📺 *Serial qo\'shish*\n\n"
        "1️⃣ Serial *kodini* yuboring\\. _Masalan:_ `155`\n\n"
        "/bekor — bekor qilish",
        parse_mode="MarkdownV2",
    )


@admin_only
async def adm_series_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = (
        "📺 *Serial qo\'shish*\n\n"
        "1️⃣ Serial *kodini* yuboring\\. _Masalan:_ `155`\n\n"
        "/bekor — bekor qilish"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    else:
        await update.callback_query.message.reply_text(text, parse_mode="MarkdownV2")
    return WAIT_SER_CODE


async def adm_series_get_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    if len(code) < 1 or len(code) > 50:
        await update.message.reply_text("⚠️ Kod 1-50 belgidan iborat bo\'lishi kerak. Qayta kiriting:")
        return WAIT_SER_CODE
    existing = get_movie(code)
    if existing and not existing.get("is_series"):
        await update.message.reply_text(
            f"⚠️ `{escape_md(code)}` kodi oddiy kino sifatida mavjud. Boshqa kod kiriting:",
            parse_mode="MarkdownV2",
        )
        return WAIT_SER_CODE
    ctx.user_data["ser_code"] = code
    parts_count = len(existing.get("parts", [])) if existing else 0
    if existing and existing.get("is_series"):
        await update.message.reply_text(
            f"✅ `{escape_md(code)}` serial topildi, hozir `{parts_count}` qism bor.\n\n"
            f"2️⃣ Serial *nomini* yuboring \\(o'zgartirish uchun\\):",
            parse_mode="MarkdownV2",
        )
    else:
        await update.message.reply_text(
            f"✅ Kod: `{escape_md(code)}`\n\n2️⃣ Serial *nomini* yuboring:",
            parse_mode="MarkdownV2",
        )
    return WAIT_SER_CAPTION


async def adm_series_get_caption(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    caption = update.message.text.strip()
    if not caption:
        await update.message.reply_text("⚠️ Nom bo\'sh bo\'lmasin. Qayta kiriting:")
        return WAIT_SER_CAPTION
    code = ctx.user_data["ser_code"]
    save_series(code, caption)
    ctx.user_data["ser_caption"] = caption
    existing = get_movie(code)
    parts_count = len(existing.get("parts", [])) if existing else 0
    await update.message.reply_text(
        f"✅ *{escape_md(caption)}* saqlandi\\!\n\n"
        f"3️⃣ Endi qismlarni *ketma\\-ket* yuboring\\. "
        f"Hozir `{parts_count}` qism bor\\.\n\n"
        f"Barcha qismlarni yuborgach /done yozing\\.",
        parse_mode="MarkdownV2",
    )
    return WAIT_SER_PARTS


async def adm_series_get_part(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = ctx.user_data.get("ser_code")
    if not code:
        await update.message.reply_text("⚠️ Jarayon buzildi. Qayta boshlang.")
        return ConversationHandler.END

    if update.message.video:
        file_id, file_type = update.message.video.file_id, "video"
    elif update.message.document:
        file_id, file_type = update.message.document.file_id, "document"
    else:
        await update.message.reply_text("❌ Faqat video yoki fayl yuboring.")
        return WAIT_SER_PARTS

    part_num = add_series_part(code, file_id, file_type)
    await update.message.reply_text(
        f"✅ *{part_num}\\-qism* qo'shildi\\. Keyingisini yuboring yoki /done yozing\\.",
        parse_mode="MarkdownV2",
    )
    return WAIT_SER_PARTS


async def adm_series_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = ctx.user_data.get("ser_code")
    if not code:
        await update.message.reply_text("⚠️ Jarayon buzildi.")
        ctx.user_data.clear()
        return ConversationHandler.END

    movie = get_movie(code)
    parts_count = len(movie.get("parts", [])) if movie else 0
    caption = movie.get("caption", code) if movie else code
    share_url = f"https://t.me/{BOT_USERNAME}?start={code}"

    await update.message.reply_text(
        f"✅ *Serial saqlandi\\!*\n\n"
        f"📌 Kod: `{escape_md(code)}`\n"
        f"📺 Nomi: *{escape_md(caption)}*\n"
        f"🎬 Qismlar: `{parts_count}` ta\n\n"
        f"🔗 Havola: `{escape_md(share_url)}`",
        parse_mode="MarkdownV2",
    )
    ctx.user_data.clear()
    return ConversationHandler.END


def add_series_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("series", adm_series_start),
            CallbackQueryHandler(adm_series_start, pattern="^adm_series$"),
        ],
        states={
            WAIT_SER_CODE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_series_get_code)],
            WAIT_SER_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_series_get_caption)],
            WAIT_SER_PARTS: [
                MessageHandler(filters.VIDEO | filters.Document.ALL, adm_series_get_part),
                CommandHandler("done", adm_series_done),
            ],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
        allow_reentry=True,
        per_message=False,
        conversation_timeout=600,
    )

def broadcast_conv() -> ConversationHandler:
    """Broadcast faqat matn kutadi — entry_point CommandHandler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("broadcast_start", _broadcast_entry),
        ],
        states={
            WAIT_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_get_text)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
        allow_reentry=True,
        per_message=False,
        conversation_timeout=300,
    )


async def _broadcast_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Faqat ichki ishlatish uchun — callback orqali chaqirilmaydi."""
    await update.message.reply_text(
        "📣 *Broadcast*\n\nHammaga yubormoqchi bo'lgan xabaringizni yuboring\\.\n\n/bekor — bekor qilish",
        parse_mode="MarkdownV2",
    )
    return WAIT_BROADCAST


# ─── Handlerlar ro'yxati ──────────────────────────────────
def get_admin_handlers():
    return [
        # ConversationHandler lar — AVVAL
        add_movie_conv(),
        del_movie_conv(),
        add_channel_conv(),
        add_series_conv(),
        broadcast_conv(),

        # Oddiy commandlar
        CommandHandler("admin",     admin_panel),
        CommandHandler("broadcast", broadcast_cmd),
        CommandHandler("series",    adm_series_start),

        # Callback router — ENG OXIRDA
        CallbackQueryHandler(
            admin_callback,
            pattern="^(adm_|confirm_del_|cancel_del|ch_del_)"
        ),
    ]
    
    # git add .
    # git commit -m "Admin panel va serial qo'shish funksiyasi qo'shildi"
    # git push origin master