from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re
from urllib.parse import quote

from config import BOT_USERNAME
from utils.db import get_movie, register_user, inc_requests, inc_downloads, get_channels
from utils.subscription import check_subscription, get_subscribe_keyboard


SUBSCRIBE_TEXT = "⚠️ Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:"
NOT_FOUND_TEXT = "❌ Bunday kod topilmadi\\. Kino kodini to'g'ri kiriting\\."


def esc(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


def welcome_text(user) -> str:
    name = esc(user.full_name or user.first_name or "Foydalanuvchi")
    return (
        f"*👋 Assalomu alaykum* [{name}](tg://user?id={user.id}) *botimizga xush kelibsiz\\!*\n\n"
        "_✍🏻 Kino kodini yuboring\\._"
    )


def build_caption(movie: dict) -> str:
    code      = esc(movie["code"])
    caption   = esc(movie["caption"])
    downloads = movie.get("downloads", 0)
    bot       = esc(f"@{BOT_USERNAME}")
    return (
        f"*🎬 \\#{code}*\n\n"
        f"*‣ Film nomi: {caption}*\n\n"
        f"*🗂 Yuklash: {downloads}*\n\n"
        f"*🤖 Bizning bot: {bot}*"
    )


def build_keyboard(movie: dict) -> InlineKeyboardMarkup:
    share_url  = quote(f"https://t.me/{BOT_USERNAME}?start={movie['code']}", safe="")
    share_text = quote(f"🎬 {movie['caption']}", safe="")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text="📤 Do'stlarga ulashish",
            url=f"https://t.me/share/url?url={share_url}&text={share_text}"
        )
    ]])


async def send_movie(update: Update, movie: dict):
    inc_downloads(movie["code"])
    movie    = get_movie(movie["code"])
    caption  = build_caption(movie)
    keyboard = build_keyboard(movie)

    # Serial bo'lsa — barcha qismlarni ketma-ket yuboramiz
    if movie.get("is_series"):
        parts = movie.get("parts", [])
        if not parts:
            await update.message.reply_text("⚠️ Hozircha qismlar yo'q.")
            return
        # Birinchi qismga caption va keyboard, qolganlariga yo'q
        for i, part in enumerate(parts):
            is_first = (i == 0)
            is_last  = (i == len(parts) - 1)
            kw = {
                "caption":    caption if is_first else f"*📺 {i + 1}\\-qism*",
                "parse_mode": ParseMode.MARKDOWN_V2,
            }
            if is_last:
                kw["reply_markup"] = keyboard
            if part["file_type"] == "video":
                await update.message.reply_video(video=part["file_id"], **kw)
            else:
                await update.message.reply_document(document=part["file_id"], **kw)
        return

    # Oddiy kino
    if movie["file_type"] == "video":
        await update.message.reply_video(
            video=movie["file_id"],
            caption=caption,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_document(
            document=movie["file_id"],
            caption=caption,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )


async def check_and_warn_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not await check_subscription(ctx.bot, user.id):
        if get_channels():
            await update.message.reply_text(
                SUBSCRIBE_TEXT,
                reply_markup=get_subscribe_keyboard(BOT_USERNAME)
            )
        return False
    return True


async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "", user.full_name or "")
    if not await check_and_warn_subscription(update, ctx):
        return
    await update.message.reply_text(welcome_text(user), parse_mode=ParseMode.MARKDOWN_V2)


async def check_sub_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await check_subscription(ctx.bot, query.from_user.id):
        await query.answer("❌ Hali obuna bo'lmadingiz!", show_alert=True)
        await query.message.reply_text(
            SUBSCRIBE_TEXT,
            reply_markup=get_subscribe_keyboard(BOT_USERNAME),
        )
        return
    await query.message.delete()
    await ctx.bot.send_message(
        chat_id=query.from_user.id,
        text=welcome_text(query.from_user),
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def movie_search_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Admin broadcast matn kutayotgan bo'lsa — broadcast qilamiz
    if ctx.user_data.get("awaiting_broadcast"):
        ctx.user_data.pop("awaiting_broadcast")
        from handlers.admin import _do_broadcast
        await _do_broadcast(update, ctx, text)
        return

    if not await check_and_warn_subscription(update, ctx):
        return
    movie = get_movie(text)
    inc_requests()
    if not movie:
        await update.message.reply_text(NOT_FOUND_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
        return
    await send_movie(update, movie)


async def start_with_code_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "", user.full_name or "")
    if not ctx.args:
        await start_handler(update, ctx)
        return
    code = ctx.args[0].upper()
    if not await check_and_warn_subscription(update, ctx):
        ctx.user_data["pending_code"] = code
        return
    movie = get_movie(code)
    if not movie:
        await start_handler(update, ctx)
        return
    await send_movie(update, movie)