from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from utils.db import get_channels


async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Barcha majburiy kanallarga obuna bo'lganini tekshiradi."""
    channels = get_channels()
    if not channels:
        return True  # Hech qanday kanal yo'q — o'tkazib yuborish

    for ch_id, ch_data in channels.items():
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                return False
        except Exception:
            return False  # Botni kanalga qo'shmagan bo'lsa
    return True


def get_subscribe_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """Majburiy kanallar tugmalarini qaytaradi."""
    channels = get_channels()
    buttons = []
    for ch_data in channels.values():
        buttons.append([InlineKeyboardButton(
            text=f"📢 {ch_data['title']}",
            url=ch_data["link"]
        )])
    buttons.append([InlineKeyboardButton(
        text="✅ Obuna bo'ldim",
        callback_data="check_sub"
    )])
    return InlineKeyboardMarkup(buttons)