import os
import asyncio

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ---------------- TOKEN ---------------- #

TOKEN = os.getenv("8729447640:AAEn47uvLdal9qhLkvHMGOLpx2-p_xmmDLw")

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not found!")

# ---------------- BOT ---------------- #

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()

# ---------------- AUTO DELETE ---------------- #

async def auto_delete(chat_id, user_msg_id=None, bot_msg_id=None):
    await asyncio.sleep(10)

    try:
        if user_msg_id:
            await bot.delete_message(chat_id, user_msg_id)
    except Exception:
        pass

    try:
        if bot_msg_id:
            await bot.delete_message(chat_id, bot_msg_id)
    except Exception:
        pass

# ---------------- START ---------------- #

@dp.message(CommandStart())
async def start_handler(message: types.Message):

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇮🇳 Hindi",
                    callback_data="lang_hi"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🇺🇸 English",
                    callback_data="lang_en"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗣 Hinglish",
                    callback_data="lang_hinglish"
                )
            ]
        ]
    )

    sent = await message.answer(
        "🌍 Please select your language:",
        reply_markup=keyboard
    )

    asyncio.create_task(
        auto_delete(
            message.chat.id,
            message.message_id,
            sent.message_id
        )
    )

# ---------------- LANGUAGE SELECT ---------------- #

@dp.callback_query(F.data == "lang_hinglish")
async def hinglish_selected(callback: types.CallbackQuery):

    text = """
🍿 <b>Hellooww! Me ek new bot hu jo Nobi ne banaya hai 🥺✨</b>

Yaha ap lagbhag sari OTT ki:
🎬 Movies
📺 Series
🍥 Anime
🇰🇷 K-Drama

search, stream aur download kar sakte ho 💫

🔥 <b>Available OTT Platforms:</b>

1. Trending
2. Netflix
3. Prime Video
4. K-Drama
5. Apple TV
6. JioHotstar
7. SonyLIV
8. Zee5
9. MX Player
10. Crunchyroll

━━━━━━━━━━━━━━━

📌 <b>Commands:</b>

🔍 /search movie_name
▶ /movie movie_name
🔥 /netflix
📂 /m3u movie_name playlist_name
📊 /analysis

━━━━━━━━━━━━━━━

✨ Enjoy your binge journey with Movies Paglu 🥺🍿
"""

    sent = await callback.message.answer(text)

    await callback.answer(
        "Language set to Hinglish 🥺"
    )

    asyncio.create_task(
        auto_delete(
            callback.message.chat.id,
            bot_msg_id=sent.message_id
        )
    )

# ---------------- MAIN ---------------- #

async def main():
    print("✅ Bot Started Successfully...")
    await dp.start_polling(bot)

# ---------------- RUN ---------------- #

if __name__ == "__main__":
    asyncio.run(main())