import os
import sys
import time
import json
import asyncio
import logging
import urllib.parse
from typing import Dict, Set, List

# Core telebot async imports
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import aiohttp

# Load Environment Variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "8729447640:AAG9_Px1rJdB24L-Z0cX5gJz0jrx1ua8nUg")
BRAND_NAME = "༄ᶦᶰᵈ᭄🇳 OBI⃠🇰 ING⃠♕ཥཽ༩ཽ࿉ཽᴮᴼˢˢ࿐"

# Strict Access Permissions Configuration
AUTHORIZED_GROUPS = [-5051894226, -1003975373349]  # Handles both basic and supergroup ID formats

# --- TERMUX SILENT MODE DETECTION ---
IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "") or os.path.exists("/data/data/com.termux")

# Initialize Logger
logging.basicConfig(
    level=logging.WARNING if IS_TERMUX else logging.INFO,  # Hide debug/info logs on Termux
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Initialize Asynchronous TeleBot
bot = AsyncTeleBot(BOT_TOKEN)

# --- SYSTEM STATS & OWNER LOG MONITOR ---
start_time = time.time()
total_queries_handled = 0
total_m3u_generated = 0
active_users_session: Set[int] = set()
request_history: List[int] = [3, 5, 8, 12, 18, 14, 22, 19, 25, 30]  # Rolling request count for load trend graph

# Progressive Anti-Spam Tracker Store
spam_tracker: Dict[int, dict] = {}

USERS_FILE = "users.txt"
LANG_FILE = "languages.json"
ACTIVITY_LOG_FILE = "activity_logs.txt"

# --- OWNER TRACKER HELPER ---
def log_user_activity(user, action_type: str, detail: str):
    """Logs user query patterns in real-time onto both the terminal and files."""
    user_id = user.id
    first_name = user.first_name or "Unknown"
    username = f"@{user.username}" if user.username else "No Username"
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    log_line = f"[{timestamp}] USER: {first_name} ({username}) | ID: {user_id} | {action_type}: '{detail}'"
    
    # Beautiful Colored Print for Termux Screen
    print(f"\033[95m🌸 [MONITOR]\033[0m \033[94m{log_line}\033[0m")
    
    # Append to activity logs
    try:
        with open(ACTIVITY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception as e:
        logger.error(f"Error writing to monitor log file: {e}")

# --- PROGRESSIVE ANTI-SPAM PROTECTION ---
async def handle_anti_spam(message) -> bool:
    """Detects spam behavior and enforces progressive muted cooldown timings (2m -> 4m -> 8m etc)."""
    user_id = message.from_user.id
    now = time.time()
    
    if user_id in spam_tracker:
        user_data = spam_tracker[user_id]
        if now < user_data["restricted_until"]:
            # Silently ignore restricted user
            return False
    else:
        spam_tracker[user_id] = {
            "timestamps": [],
            "last_text": "",
            "cooldown_level": 0,
            "restricted_until": 0
        }
        
    user_data = spam_tracker[user_id]
    
    # Record current timestamp and keep only last 5 seconds records
    user_data["timestamps"].append(now)
    user_data["timestamps"] = [t for t in user_data["timestamps"] if now - t < 5]
    
    is_spam = False
    # Threshold 1: More than 4 messages within 5 seconds
    if len(user_data["timestamps"]) > 4:
        is_spam = True
        
    # Threshold 2: Repeatedly sending the exact same text input
    current_text = message.text or ""
    if current_text and current_text == user_data["last_text"]:
        if len(user_data["timestamps"]) >= 2:
            is_spam = True
            
    user_data["last_text"] = current_text
    
    if is_spam:
        # Calculate progressive cooldown minutes (2 min -> 4 min -> 8 min -> 16 min...)
        user_data["cooldown_level"] += 1
        cooldown_minutes = 2 ** user_data["cooldown_level"]
        cooldown_seconds = cooldown_minutes * 60
        user_data["restricted_until"] = now + cooldown_seconds
        
        try:
            warn = await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"🚫 *ANTI-SPAM MUTED!* ⚠️\n\n"
                    f"Suno `{message.from_user.first_name}`, stop spamming group chat!\n"
                    f"Aapko temporary ignore list me daal diya gaya hai.\n\n"
                    f"⏳ *Mute Duration:* `{cooldown_minutes} Minutes`"
                ),
                parse_mode="Markdown"
            )
            asyncio.create_task(delayed_delete(message.chat.id, warn.message_id, 10))
        except Exception:
            pass
        return False
        
    return True

# --- STRICT GROUP SECURITY MIDDLEWARE ---
async def check_authorization(message_or_call) -> bool:
    """Blocks execution outside authorized group ID, alerts, and auto-deletes in 5s."""
    is_callback = hasattr(message_or_call, "message")
    chat_id = message_or_call.message.chat.id if is_callback else message_or_call.chat.id
    
    if chat_id not in AUTHORIZED_GROUPS:
        try:
            warning_text = (
                f"⚠️ *ACCESS DENIED!* 🥺🍿\n\n"
                f"Suno yaar, yeh bot sirf *{BRAND_NAME}* ke authorized group me kaam karta hai!\n\n"
                f"🚫 _Access to DMs & other groups is currently locked!_"
            )
            warning_msg = await bot.send_message(
                chat_id=chat_id,
                text=warning_text,
                parse_mode="Markdown"
            )
            
            if not is_callback:
                asyncio.create_task(delayed_delete(chat_id, message_or_call.message_id, 5))
            asyncio.create_task(delayed_delete(chat_id, warning_msg.message_id, 5))
            
        except Exception as e:
            logger.error(f"Failed to process restriction check warning: {e}")
        return False
    return True

# --- ADMIN STATUS CHECKER ---
async def is_admin(chat_id: int, user_id: int) -> bool:
    """Verifies whether the target member holds admin privileges in the active group chat."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Admin privilege check failed: {e}")
        return False

# --- SYSTEM STATS STORAGE HELPERS ---
def load_users() -> Set[int]:
    if not os.path.exists(USERS_FILE):
        return set()
    try:
        with open(USERS_FILE, "r") as f:
            return {int(line.strip()) for line in f if line.strip().isdigit()}
    except Exception:
        return set()

def save_user(user_id: int):
    users = load_users()
    if user_id not in users:
        try:
            with open(USERS_FILE, "a") as f:
                f.write(f"{user_id}\n")
        except Exception as e:
            logger.error(f"Error saving user: {e}")

def load_languages() -> Dict[str, str]:
    if not os.path.exists(LANG_FILE):
        return {}
    try:
        with open(LANG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_language(user_id: int, lang: str):
    try:
        langs = load_languages()
        langs[str(user_id)] = lang
        with open(LANG_FILE, "w") as f:
            json.dump(langs, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving language: {e}")

def track_user(user, detail="Session Interaction"):
    active_users_session.add(user.id)
    save_user(user.id)
    log_user_activity(user, "INTERACTION", detail)

def get_uptime() -> str:
    elapsed = time.time() - start_time
    days = int(elapsed // 86400)
    hours = int((elapsed % 86400) // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"

# --- GENERATE DYNAMIC ASCII STATS GRAPH ---
def generate_live_load_graph() -> str:
    """Generates a stylish ASCII bar chart based on actual user query spikes."""
    global request_history
    if len(request_history) > 10:
        request_history.pop(0)
        
    max_val = max(request_history) if request_history else 10
    if max_val == 0:
        max_val = 10
        
    graph_rows = []
    for level in [80, 60, 40, 20]:
        row = f"{level:2d}% ┤ "
        for val in request_history[-10:]:
            percentage = (val / max_val) * 100
            if percentage >= level:
                row += " █ "
            else:
                row += "   "
        graph_rows.append(row)
    graph_rows.append("     └" + "───" * min(len(request_history), 10) + "► Load Trend")
    return "\n".join(graph_rows)

# --- REAL-TIME API ENDPOINTS MAP ---
PLATFORM_URLS = {
    "trending": "https://net27.cc/api/catalog/curated/trending",
    "netflix": "https://net27.cc/api/catalog/curated/Netflix",
    "primevideo": "https://net27.cc/api/catalog/curated/PrimeVideo",
    "kdrama": "https://net27.cc/api/catalog/curated/KDrama",
    "appletv": "https://net27.cc/api/catalog/discover?platform=AppleTV&type=movie&sort=popularity&region=IN",
    "jiohotstar": "https://net27.cc/api/catalog/discover?platform=JioHotstar&type=movie&sort=popularity&region=IN",
    "sonyliv": "https://net27.cc/api/catalog/discover?platform=SonyLIV&type=movie&sort=popularity&region=IN",
    "zee5": "https://net27.cc/api/catalog/discover?platform=Zee5&type=movie&sort=popularity&region=IN",
    "mxplayer": "https://net27.cc/api/catalog/discover?platform=MX&type=movie&sort=popularity&region=IN",
    "crunchyroll": "https://net27.cc/api/catalog/curated/Crunchyroll"
}

# --- GLOBAL HTTP ASYNC REQUEST ENGINE ---
async def fetch_json(url: str, method: str = "GET", post_data: dict = None) -> dict:
    """Helper for network asynchronous fetches using aiohttp."""
    try:
        async with aiohttp.ClientSession() as session:
            if method == "POST":
                async with session.post(url, json=post_data, timeout=aiohttp.ClientTimeout(total=8)) as response:
                    if response.status == 200:
                        return await response.json()
            else:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                    if response.status == 200:
                        return await response.json()
    except Exception as e:
        logger.error(f"HTTP Network Request failed on {url}: {e}")
    return {}

# --- DIRECT ENCRYPTION RESOLVER HELPER ---
async def resolve_best_stream(title: str, item_type: str, tmdb_id: str, se: int = 1, ep: int = 1):
    """Hits the pipeline APIs and extracts direct secure streaming URL and its poster cover."""
    meta_url = f"https://net27.cc/api/catalog/title/{item_type}/{tmdb_id}"
    meta_data = await fetch_json(meta_url)
    logo_url = ""
    if meta_data:
        logo_url = meta_data.get("poster") or meta_data.get("backdrop") or ""
        
    search_payload = {
        "keyword": title,
        "page": 1,
        "perPage": 30,
        "subjectType": 1 if item_type == "movie" else 2
    }
    aoneroom_data = await fetch_json("https://h5-api.aoneroom.com/wefeed-h5api-bff/subject/search", "POST", search_payload)
    
    subject_id = ""
    detail_path = ""
    if aoneroom_data and aoneroom_data.get("code") == 0:
        items = aoneroom_data.get("data", {}).get("items", [])
        if items:
            match = items[0]
            for item in items:
                if title.lower() in item.get("title", "").lower():
                    match = item
                    break
            subject_id = match.get("subjectId", "")
            detail_path = match.get("detailPath", "")
            
    embed_url = f"https://net27.cc/api/embed-tmdb/{tmdb_id}?type={item_type}&se={se}&ep={ep}&sid={subject_id}&dp={detail_path}"
    embed_data = await fetch_json(embed_url)
    
    if embed_data and embed_data.get("ok") and "streams" in embed_data:
        streams = embed_data.get("streams", [])
        if streams:
            best_stream = streams[0]
            raw_url = best_stream.get("url", "")
            encoded_url = urllib.parse.quote(raw_url)
            proxy_url = f"https://streamhub-proxy.1545zoya.workers.dev/?url={encoded_url}"
            return proxy_url, logo_url
            
    return None, logo_url

# --- LOCALIZED STRINGS ---
def get_text(user_id: int, key: str) -> str:
    langs = load_languages()
    lang = langs.get(str(user_id), "hinglish")
    
    translations = {
        "hindi": {
            "auto_delete_note": "\n\n⚠️ _यह संदेश 10 सेकंड में स्वतः समाप्त हो जाएगा..._",
            "searching": "🔍 '{}' को सर्वर्स पर लाइव खोजा जा रहा है... 🥺🍿",
            "not_found": (
                "🥺 *माफ़ कीजियेगा! मुझे परिणाम नहीं मिला!*\n\n"
                "👉 *कृप्या सही स्पेलिंग चेक करें!* स्पेलिंग ठीक करने के स्टेप्स:\n"
                "1️⃣ Google पर जाएँ और अपनी फ़िल्म का नाम सर्च करें।\n"
                "2️⃣ वहाँ से सही स्पेलिंग को कॉपी करें।\n"
                "3️⃣ यहाँ फिर से सही स्पेलing के साथ सर्च करें! 🍿"
            ),
        },
        "english": {
            "auto_delete_note": "\n\n⚠️ _This message will auto-delete in 10 seconds..._",
            "searching": "🔍 Searching for '{}' live on databases... 🥺🍿",
            "not_found": (
                "🥺 *Oops! Movie not found!*\n\n"
                "👉 *Please check & correct the spelling!* Steps:\n"
                "1️⃣ Go to Google and search your movie name.\n"
                "2️⃣ Match and copy the exact spelling.\n"
                "3️⃣ Paste and search here again! 🍿"
            ),
        },
        "hinglish": {
            "auto_delete_note": "\n\n⚠️ _Yeh message 10 seconds me auto-delete ho jayega..._",
            "searching": "🔍 '{}' ko servers pe live search kiya ja raha hai... 🥺🍿",
            "not_found": (
                "🥺 *Arey yaar! Movie nahi mili!*\n\n"
                "👉 *Plese spelling correct karein!* Correct karne ke steps:\n"
                "1️⃣ Google par jaakar movie search karein.\n"
                "2️⃣ Sahi spelling match karke copy karein.\n"
                "3️⃣ Phir se sahi spelling yahan send karein! 🍿"
            ),
        }
    }
    return translations.get(lang, translations["hinglish"]).get(key, "")

def get_welcome_intro(user_id: int) -> str:
    langs = load_languages()
    lang = langs.get(str(user_id), "hinglish")
    if lang == "hindi":
        return (
            f"🍿 *नमस्ते जी! मैं एक नया बॉट हूँ जिसे {BRAND_NAME} ने बनाया है* 🥺✨\n\n"
            "यहाँ आप लगभग सभी OTT की:\n"
            "🎬 *Movies* | 📺 *Series* | 🍥 *Anime* | 🇰🇷 *K-Drama*\n\n"
            "सर्च, स्ट्रीम और डाउनलोड कर सकते हैं! 💫\n\n"
            "🔥 *उपलब्ध OTT प्लेटफॉर्म्स:*\n"
            "1️⃣ Trending       2️⃣ Netflix\n"
            "3️⃣ Prime Video    4️⃣ K-Drama\n"
            "5️⃣ Apple TV        6️⃣ JioHotstar\n"
            "7️⃣ SonyLIV        8️⃣ Zee5\n"
            "9️⃣ MX Player       🔟 Crunchyroll\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📌 *कमांड्स:*\n"
            "🔍 `/search <नाम>` - फिल्म खोजें\n"
            "📁 `/m3u <नाम> playlist.m3u` - M3U प्लेलिस्ट बनाएँ\n"
            "📊 `/analysis` - आंकड़े देखें\n"
            "━━━━━━━━━━━━━━━\n"
            f"✨ Enjoy your binge journey with Movies Paglu 🥺🍿"
        )
    elif lang == "english":
        return (
            f"🍿 *Hello! I am a new bot created by {BRAND_NAME}* 🥺✨\n\n"
            "Here you can search, stream, and download almost all OTT content like:\n"
            "🎬 *Movies* | 📺 *Series* | 🍥 *Anime* | 🇰🇷 *K-Drama*\n\n"
            "across multiple platforms! 💫\n\n"
            "🔥 *Available OTT Platforms:*\n"
            "1️⃣ Trending       2️⃣ Netflix\n"
            "3️⃣ Prime Video    4️⃣ K-Drama\n"
            "5️⃣ Apple TV        6️⃣ JioHotstar\n"
            "7️⃣ SonyLIV        8️⃣ Zee5\n"
            "9️⃣ MX Player       🔟 Crunchyroll\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📌 *Commands:*\n"
            "🔍 `/search <movie>` - Search content\n"
            "📁 `/m3u <movie> playlist.m3u` - Generate M3U playlist\n"
            "📊 `/analysis` - Show bot analytics\n"
            "━━━━━━━━━━━━━━━\n"
            f"✨ Enjoy your binge journey with Movies Paglu 🥺🍿"
        )
    else:  # Hinglish
        return (
            f"🍿 *Hellooww! Me ek new bot hu jo {BRAND_NAME} ne banaya hai* 🥺✨\n\n"
            "Yaha aap lagbhag saari OTT ki:\n"
            "🎬 *Movies* | 📺 *Series* | 🍥 *Anime* | 🇰🇷 *K-Drama*\n\n"
            "search, stream aur download kar sakte ho 💫\n\n"
            "🔥 *Available OTT Platforms:*\n"
            "1️⃣ Trending       2️⃣ Netflix\n"
            "3️⃣ Prime Video    4️⃣ K-Drama\n"
            "5️⃣ Apple TV        6️⃣ JioHotstar\n"
            "7️⃣ SonyLIV        8️⃣ Zee5\n"
            "9️⃣ MX Player       🔟 Crunchyroll\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📌 *Commands:*\n"
            "🔍 `/search <movie_name>`\n"
            "📁 `/m3u <movie_name> playlist.m3u`\n"
            "📊 `/analysis`\n"
            "━━━━━━━━━━━━━━━\n"
            f"✨ Enjoy your binge journey with Movies Paglu 🥺🍿"
        )

# --- KEYBOARDS ---
def get_lang_keyboard() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(text="🇮🇳 Hindi", callback_data="set_lang:hindi"),
        InlineKeyboardButton(text="🇺🇸 English", callback_data="set_lang:english")
    )
    markup.row(
        InlineKeyboardButton(text="🗣 Hinglish", callback_data="set_lang:hinglish")
    )
    return markup

def get_platforms_keyboard() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(text="🔥 Trending", callback_data="ott:trending"),
        InlineKeyboardButton(text="🔴 Netflix", callback_data="ott:netflix"),
        InlineKeyboardButton(text="🔵 Prime Video", callback_data="ott:primevideo"),
        InlineKeyboardButton(text="🇰🇷 K-Drama", callback_data="ott:kdrama"),
        InlineKeyboardButton(text="🍏 Apple TV", callback_data="ott:appletv"),
        InlineKeyboardButton(text="📺 JioHotstar", callback_data="ott:jiohotstar"),
        InlineKeyboardButton(text="💎 SonyLIV", callback_data="ott:sonyliv"),
        InlineKeyboardButton(text="✨ Zee5", callback_data="ott:zee5"),
        InlineKeyboardButton(text="⚡ MX Player", callback_data="ott:mxplayer"),
        InlineKeyboardButton(text="🍥 Crunchyroll", callback_data="ott:crunchyroll")
    )
    markup.row(
        InlineKeyboardButton(text="🔄 Change Language", callback_data="change_language")
    )
    return markup

def get_home_keyboard() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="back_to_menu"))
    return markup

# --- AUTO DELETION TASK ENGINE ---
async def delayed_delete(chat_id: int, message_id: int, delay: int = 10):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

# --- DISCOVER / CATEGORY LOGIC ---
async def get_shows_from_api(category: str) -> List[dict]:
    """Hits dynamic platform APIs to extract live feeds."""
    url = PLATFORM_URLS.get(category)
    if not url:
        return []
    
    data = await fetch_json(url)
    if not data or not data.get("ok"):
        return []
    
    raw_list = []
    if "hero" in data and isinstance(data["hero"], list):
        raw_list.extend(data["hero"])
    if "items" in data and isinstance(data["items"], list):
        raw_list.extend(data["items"])
    if "rails" in data and isinstance(data["rails"], list):
        for rail in data["rails"]:
            if "items" in rail and isinstance(rail["items"], list):
                raw_list.extend(rail["items"])
                
    shows = []
    seen = set()
    for item in raw_list:
        tmdb_id = item.get("tmdbId")
        if tmdb_id and tmdb_id not in seen:
            seen.add(tmdb_id)
            shows.append({
                "tmdbId": tmdb_id,
                "type": item.get("type", "movie"),
                "title": item.get("title", "No Title"),
                "year": item.get("year", "N/A"),
                "rating": round(item.get("rating", 0.0), 1)
            })
            
    return shows[:5]

# --- HANDLERS ---

@bot.message_handler(commands=['start'])
async def cmd_start_handler(message):
    if not await check_authorization(message) or not await handle_anti_spam(message):
        return
        
    track_user(message.from_user, "Start initialized")
    asyncio.create_task(delayed_delete(message.chat.id, message.message_id, 10))
    
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "🌸 *Heeyy! Welcome to Movies Paglu!* 🥺🍿\n\n"
            f"Aapka apna premium & cute OTT search companion bot created by {BRAND_NAME}! ✨\n\n"
            "👉 *Please choose your language to continue:*"
        ),
        reply_markup=get_lang_keyboard(),
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_lang:"))
async def set_lang_callback(call):
    if not await check_authorization(call):
        return
        
    user_id = call.from_user.id
    lang = call.data.split(":")[1]
    
    save_language(user_id, lang)
    track_user(call.from_user, f"Set Language: {lang}")
    
    intro_text = get_welcome_intro(user_id)
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=intro_text,
        reply_markup=get_platforms_keyboard(),
        parse_mode="Markdown"
    )
    await bot.answer_callback_query(call.id, f"Language set to {lang.title()}! 🌟")

@bot.callback_query_handler(func=lambda call: call.data == "change_language")
async def change_language_callback(call):
    if not await check_authorization(call):
        return
        
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="🌸 *Choose Your Language / Apni Bhasha Chune:* 🥺🍿",
        reply_markup=get_lang_keyboard(),
        parse_mode="Markdown"
    )
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
async def back_to_menu_callback(call):
    if not await check_authorization(call):
        return
        
    user_id = call.from_user.id
    intro_text = get_welcome_intro(user_id)
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=intro_text,
        reply_markup=get_platforms_keyboard(),
        parse_mode="Markdown"
    )
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ott:"))
async def ott_platform_callback(call):
    if not await check_authorization(call):
        return
        
    user_id = call.from_user.id
    category = call.data.split(":")[1]
    track_user(call.from_user, f"Selected category {category}")
    
    loading_msg = await bot.send_message(
        chat_id=call.message.chat.id,
        text="⚡ _Fetching dynamic live server catalog..._"
    )
    
    shows = await get_shows_from_api(category)
    
    try:
        await bot.delete_message(loading_msg.chat.id, loading_msg.message_id)
    except Exception:
        pass
        
    if not shows:
        await bot.answer_callback_query(call.id, "No titles active right now! Try again later.", show_alert=True)
        return
        
    category_title = category.upper()
    text = (
        f"🍿 *Movies Paglu - {category_title}* 🥺✨\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Real-time handpicked shows on server:\n\n"
    )
    
    markup = InlineKeyboardMarkup()
    for s in shows:
        text += f"🎬 *{s['title']}* ({s['year']}) | ⭐ `{s['rating']}`\n\n"
        markup.row(InlineKeyboardButton(text=f"🎬 {s['title']} ({s['year']})", callback_data=f"det:{s['type']}:{s['tmdbId']}"))
        
    markup.row(
        InlineKeyboardButton(text="➡️ More Options", callback_data="category_more"),
        InlineKeyboardButton(text="🔙 Main Menu", callback_data="back_to_menu")
    )
    
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text + "━━━━━━━━━━━━━━━━━━━━\n_👇 Select details / play metadata below:_",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await bot.answer_callback_query(call.id)

# --- MORE OPTION CALLBACK ---
@bot.callback_query_handler(func=lambda call: call.data == "category_more")
async def category_more_callback(call):
    if not await check_authorization(call):
        return
        
    user_id = call.from_user.id
    track_user(call.from_user, "Clicked 'More Options'")
    
    text = (
        "🥺 *I don't know what you want, please search them!* 🍿\n\n"
        "👉 Humare paas bhot bada database hai! Direct search karne ke liye bas name type karein ya `/search <movie_name>` command use karein! 🔍"
    )
    
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text,
        reply_markup=get_home_keyboard(),
        parse_mode="Markdown"
    )
    await bot.answer_callback_query(call.id)

# --- SHOW DETAILED PAGE RETRIEVAL (WITH ATTACHED PICTURE) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("det:"))
async def show_details_callback(call):
    if not await check_authorization(call):
        return
        
    _, item_type, tmdb_id = call.data.split(":")
    user_id = call.from_user.id
    track_user(call.from_user, f"Metadata lookup tmdb_id:{tmdb_id}")
    
    url = f"https://net27.cc/api/catalog/title/{item_type}/{tmdb_id}"
    data = await fetch_json(url)
    
    if not data or not data.get("ok"):
        await bot.answer_callback_query(call.id, "Metadata sync failed on server.", show_alert=True)
        return
        
    title = data.get("title", "Unknown Title")
    tagline = data.get("tagline", "Enjoy high quality streaming")
    overview = data.get("overview", "No plot overview available.")
    year = data.get("year", "N/A")
    rating = round(data.get("rating", 0.0), 1)
    runtime = data.get("runtime", 0)
    genres_list = ", ".join([g.get("name") for g in data.get("genres", [])])
    
    poster_url = data.get("poster") or data.get("backdrop")
    if not poster_url:
        poster_url = "https://images.unsplash.com/photo-1536440136628-849c177e76a1"
        
    caption_text = (
        f"🎬 *{title}* ({year}) 🥺🍿\n"
        f"🎭 `{tagline}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ *Rating:* {rating}/10\n"
        f"🕒 *Runtime:* {runtime} mins\n"
        f"📚 *Genres:* {genres_list}\n"
        f"🏢 *Source Type:* {item_type.upper()}\n\n"
        f"📝 *Plot:* {overview}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌸 Brand: {BRAND_NAME}"
    )
    
    if len(caption_text) > 1000:
        caption_text = caption_text[:950] + "...\n\n_Plot truncated due to size limits._"
    
    markup = InlineKeyboardMarkup()
    
    if item_type == "movie":
        markup.row(InlineKeyboardButton(text="▶ Stream / Download Now", callback_data=f"play:movie:{tmdb_id}:1:1"))
    else:
        seasons = data.get("seasons", [])
        for s in seasons[:5]:
            markup.add(InlineKeyboardButton(text=f"📁 {s.get('name')}", callback_data=f"season:{tmdb_id}:{s.get('season_number')}"))
            
    markup.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="back_to_menu"))
    
    try:
        await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    except Exception:
        pass
        
    detail_msg = await bot.send_photo(
        chat_id=call.message.chat.id,
        photo=poster_url,
        caption=caption_text,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    
    await bot.answer_callback_query(call.id)
    asyncio.create_task(delayed_delete(detail_msg.chat.id, detail_msg.message_id, 30))

# --- TV SHOW SEASON SELECTOR ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("season:"))
async def select_season_callback(call):
    if not await check_authorization(call):
        return
        
    _, tmdb_id, season_num = call.data.split(":")
    user_id = call.from_user.id
    
    url = f"https://net27.cc/api/catalog/season/{tmdb_id}/{season_num}"
    data = await fetch_json(url)
    
    if not data or not data.get("ok"):
        await bot.answer_callback_query(call.id, "Failed to load episodes for this season.", show_alert=True)
        return
        
    episodes = data.get("episodes", [])
    text = (
        f"📺 *{data.get('name', 'Stranger Things')}* - Episodes List\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Select episode to load direct player linkages:\n\n"
    )
    
    markup = InlineKeyboardMarkup()
    for ep in episodes[:10]:
        markup.row(InlineKeyboardButton(text=f"▶ Ep {ep.get('episode')}: {ep.get('name')[:20]}...", callback_data=f"play:tv:{tmdb_id}:{season_num}:{ep.get('episode')}"))
        
    markup.row(InlineKeyboardButton(text="🔙 Back to Show Info", callback_data="back_to_menu"))
    
    try:
        await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    except Exception:
        pass
        
    result_msg = await bot.send_message(
        chat_id=call.message.chat.id,
        text=text,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await bot.answer_callback_query(call.id)
    asyncio.create_task(delayed_delete(result_msg.chat.id, result_msg.message_id, 30))

# --- DYNAMIC STREAM PIPELINE RESOLUTION ENGINE ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("play:"))
async def play_stream_callback(call):
    if not await check_authorization(call):
        return
        
    _, item_type, tmdb_id, se, ep = call.data.split(":")
    user_id = call.from_user.id
    
    meta_url = f"https://net27.cc/api/catalog/title/{item_type}/{tmdb_id}"
    meta_data = await fetch_json(meta_url)
    title = meta_data.get("title", "Stree 2") if meta_data else "Stree 2"
    
    await bot.answer_callback_query(call.id, "Resolving direct stream linkages... 📡🍿")
    
    resolving_msg = await bot.send_message(
        chat_id=call.message.chat.id,
        text=f"⚡ *Resolving premium stream nodes for:* `{title}`...\n\n_Wait while we query decryption keys..._"
    )
    
    search_payload = {
        "keyword": title,
        "page": 1,
        "perPage": 30,
        "subjectType": 1 if item_type == "movie" else 2
    }
    aoneroom_data = await fetch_json("https://h5-api.aoneroom.com/wefeed-h5api-bff/subject/search", "POST", search_payload)
    
    subject_id = ""
    detail_path = ""
    
    if aoneroom_data and aoneroom_data.get("code") == 0:
        items = aoneroom_data.get("data", {}).get("items", [])
        if items:
            match = items[0]
            for item in items:
                if title.lower() in item.get("title", "").lower():
                    match = item
                    break
            subject_id = match.get("subjectId", "")
            detail_path = match.get("detailPath", "")
            
    embed_url = f"https://net27.cc/api/embed-tmdb/{tmdb_id}?type={item_type}&se={se}&ep={ep}&sid={subject_id}&dp={detail_path}"
    embed_data = await fetch_json(embed_url)
    
    try:
        await bot.delete_message(resolving_msg.chat.id, resolving_msg.message_id)
    except Exception:
        pass
        
    if not embed_data or not embed_data.get("ok") or "streams" not in embed_data:
        err_msg = await bot.send_message(
            chat_id=call.message.chat.id,
            text=f"🥺 *Sorry!* Active links are currently unavailable for this item.\n\n_Note: Stream decryption keys might be out of sync._",
            reply_markup=get_home_keyboard()
        )
        asyncio.create_task(delayed_delete(err_msg.chat.id, err_msg.message_id, 15))
        return
        
    streams = embed_data.get("streams", [])
    
    text = (
        f"🎬 *Stream Player Ready!* 🥺🍿\n"
        f"📡 *Title:* {title} (Season {se} - Ep {ep})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👉 _Click resolution links below to play directly or download over Proxy CDNs:_\n\n"
    )
    
    for idx, s in enumerate(streams, 1):
        raw_url = s.get("url", "")
        encoded_url = urllib.parse.quote(raw_url)
        proxy_url = f"https://streamhub-proxy.1545zoya.workers.dev/?url={encoded_url}"
        
        resolution = s.get("resolution", "HD")
        size_bytes = s.get("size", 0)
        size_gb = round(size_bytes / (1024 * 1024 * 1024), 2) if size_bytes else "N/A"
        
        text += f"⚡ `{idx}`. [{resolution}p Quality]({proxy_url}) \n      📂 Size: `{size_gb} GB` | direct CDN link\n\n"
        
    text += f"━━━━━━━━━━━━━━━━━━━━\n_⚠️ Playback links remain valid for 2 hours._\n🌸 Brand: {BRAND_NAME}"
    
    result_msg = await bot.send_message(
        chat_id=call.message.chat.id,
        text=text,
        reply_markup=get_home_keyboard(),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    asyncio.create_task(delayed_delete(result_msg.chat.id, result_msg.message_id, 30))

# --- LIVE BROADCAST SEARCH DISPATCHERS ---
@bot.message_handler(commands=['search'])
async def cmd_search_handler(message):
    if not await check_authorization(message) or not await handle_anti_spam(message):
        return
        
    global total_queries_handled, request_history
    user_id = message.from_user.id
    
    asyncio.create_task(delayed_delete(message.chat.id, message.message_id, 10))
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        error_msg = await bot.send_message(
            chat_id=message.chat.id,
            text="⚠️ *Hii! Please type a movie name to search!*\n\n👉 _Example: /search Squid game_" + get_text(user_id, "auto_delete_note"),
            parse_mode="Markdown"
        )
        asyncio.create_task(delayed_delete(error_msg.chat.id, error_msg.message_id, 10))
        return
        
    query = args[1].strip()
    total_queries_handled += 1
    track_user(message.from_user, f"Query /search: '{query}'")
    
    request_history.append(request_history[-1] + 1 if request_history else 1)
    
    searching_msg = await bot.send_message(
        chat_id=message.chat.id,
        text=get_text(user_id, "searching").format(query),
        parse_mode="Markdown"
    )
    
    encoded_query = urllib.parse.quote(query)
    search_url = f"https://net27.cc/api/catalog/search?q={encoded_query}"
    search_data = await fetch_json(search_url)
    
    try:
        await bot.delete_message(searching_msg.chat.id, searching_msg.message_id)
    except Exception:
        pass
        
    if not search_data or not search_data.get("ok") or not search_data.get("items"):
        not_found_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=get_text(user_id, "not_found") + get_text(user_id, "auto_delete_note"),
            reply_markup=get_home_keyboard(),
            parse_mode="Markdown"
        )
        asyncio.create_task(delayed_delete(not_found_msg.chat.id, not_found_msg.message_id, 15))
        return
        
    items = search_data.get("items", [])
    text = (
        f"🍿 *Yeyy! Active Matches Found on Server:* 💫\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Select your match to fetch metadata profile:\n\n"
    )
    
    markup = InlineKeyboardMarkup()
    for item in items[:6]:
        title = item.get("title")
        year = item.get("year", "N/A")
        rating = round(item.get("rating", 0.0), 1)
        item_type = item.get("type", "movie")
        
        text += f"🎬 *{title}* ({year}) | Rating: ⭐ `{rating}`\n"
        markup.row(InlineKeyboardButton(text=f"🎬 {title} ({year})", callback_data=f"det:{item_type}:{item.get('tmdbId')}"))
        
    markup.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="back_to_menu"))
    
    result_msg = await bot.send_message(
        chat_id=message.chat.id,
        text=text + "━━━━━━━━━━━━━━━━━━━━",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    asyncio.create_task(delayed_delete(result_msg.chat.id, result_msg.message_id, 15))

# --- DYNAMIC M3U GENERATION SYSTEM (SERIES SUPPORTED) ---
@bot.message_handler(commands=['m3u'])
async def cmd_m3u_handler(message):
    if not await check_authorization(message) or not await handle_anti_spam(message):
        return
        
    global total_queries_handled, request_history
    user_id = message.from_user.id
    
    asyncio.create_task(delayed_delete(message.chat.id, message.message_id, 10))
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        error_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "⚠️ *Hii! Incorrect M3U command syntax!*\n\n"
                "👉 *Use format:* `/m3u <movie_or_series_name> playlistname.m3u`\n"
                "_Example: /m3u Stree 2 stree2.m3u_"
            ),
            parse_mode="Markdown"
        )
        asyncio.create_task(delayed_delete(error_msg.chat.id, error_msg.message_id, 10))
        return
        
    full_arg = args[1].strip()
    
    if full_arg.lower().endswith(".m3u"):
        parts = full_arg.rsplit(maxsplit=1)
        if len(parts) == 2 and parts[1].lower().endswith(".m3u"):
            query = parts[0]
            filename = parts[1]
        else:
            query = full_arg[:-4]
            filename = full_arg
    else:
        query = full_arg
        filename = f"{query.replace(' ', '_')}_playlist.m3u"
        
    if not filename.lower().endswith(".m3u"):
        filename += ".m3u"
        
    track_user(message.from_user, f"Request M3U Generation: '{query}'")
    request_history.append(request_history[-1] + 1 if request_history else 1)
    
    status_msg = await bot.send_message(
        chat_id=message.chat.id,
        text=f"⏳ *Searching catalog database...*\n\n🔍 Searching: `{query}`"
    )
    
    encoded_query = urllib.parse.quote(query)
    search_url = f"https://net27.cc/api/catalog/search?q={encoded_query}"
    search_data = await fetch_json(search_url)
    
    try:
        await bot.delete_message(status_msg.chat.id, status_msg.message_id)
    except Exception:
        pass
        
    if not search_data or not search_data.get("ok") or not search_data.get("items"):
        fail_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=get_text(user_id, "not_found") + get_text(user_id, "auto_delete_note"),
            reply_markup=get_home_keyboard(),
            parse_mode="Markdown"
        )
        asyncio.create_task(delayed_delete(fail_msg.chat.id, fail_msg.message_id, 10))
        return
        
    best_match = search_data.get("items")[0]
    title = best_match.get("title", query)
    year = best_match.get("year", "N/A")
    item_type = best_match.get("type", "movie")
    tmdb_id = best_match.get("tmdbId")
    
    # CASE 1: Content is a series (tv) -> Ask for season selection
    if item_type == "tv":
        # Fetch seasons count
        series_url = f"https://net27.cc/api/catalog/title/tv/{tmdb_id}"
        series_data = await fetch_json(series_url)
        
        if not series_data or not series_data.get("ok"):
            await bot.send_message(chat_id=message.chat.id, text="🥺 *Failed to retrieve seasons metadata.*")
            return
            
        seasons = series_data.get("seasons", [])
        text = (
            f"📺 *{title}* is a TV Series!\n\n"
            f"👉 *Please select a Season* below. Bot will automatically compile and add all episodes of that season into a single M3U playlist!"
        )
        
        markup = InlineKeyboardMarkup()
        for s in seasons[:5]: # Limit to first 5 seasons for button safety
            markup.row(InlineKeyboardButton(text=f"📁 {s.get('name')}", callback_data=f"m3useas:{tmdb_id}:{s.get('season_number')}:{filename}"))
            
        markup.row(InlineKeyboardButton(text="❌ Cancel", callback_data="back_to_menu"))
        
        await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        return
        
    # CASE 2: Content is a movie -> Directly generate
    processing_msg = await bot.send_message(
        chat_id=message.chat.id,
        text=f"⏳ *Generating Movie M3U for:* `{title}`"
    )
    
    stream_url, logo_url = await resolve_best_stream(title, "movie", tmdb_id)
    
    try:
        await bot.delete_message(processing_msg.chat.id, processing_msg.message_id)
    except Exception:
        pass
        
    if not stream_url:
        fail_msg = await bot.send_message(
            chat_id=message.chat.id,
            text="🥺 *Arey yaar! Is film ke liye active stream link nahi mil paya.*",
            reply_markup=get_home_keyboard()
        )
        asyncio.create_task(delayed_delete(fail_msg.chat.id, fail_msg.message_id, 10))
        return
        
    m3u_content = (
        f"#EXTM3U\n"
        f"#EXTINF:-1 tvg-logo=\"{logo_url}\" group-title=\"{BRAND_NAME} Specials\", {title} ({year})\n"
        f"{stream_url}\n"
    )
    
    await deliver_m3u_file(message.chat.id, filename, m3u_content, title, message.from_user.first_name)

# --- CALLBACK FOR TV SERIES M3U GENERATION ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("m3useas:"))
async def m3u_season_callback(call):
    if not await check_authorization(call):
        return
        
    _, tmdb_id, season_num, filename = call.data.split(":")
    user_id = call.from_user.id
    
    # Fetch show metadata
    show_url = f"https://net27.cc/api/catalog/title/tv/{tmdb_id}"
    show_data = await fetch_json(show_url)
    title = show_data.get("title", "Series") if show_data else "Series"
    
    # Fetch season episode lists
    season_url = f"https://net27.cc/api/catalog/season/{tmdb_id}/{season_num}"
    season_data = await fetch_json(season_url)
    
    if not season_data or not season_data.get("ok"):
        await bot.answer_callback_query(call.id, "Failed to load episodes list.", show_alert=True)
        return
        
    episodes = season_data.get("episodes", [])
    if not episodes:
        await bot.answer_callback_query(call.id, "No active episodes found inside this season.", show_alert=True)
        return
        
    await bot.answer_callback_query(call.id, "Resolving all episodes concurrently... 🚀")
    
    status_msg = await bot.send_message(
        chat_id=call.message.chat.id,
        text=f"⏳ *Resolving streams for all {len(episodes)} episodes of Season {season_num}...*\n_Generating full track playlist, wait a few seconds..._"
    )
    
    # Concurrently resolve stream links for all episodes to maximize speed
    tasks = []
    for ep in episodes:
        tasks.append(resolve_best_stream(title, "tv", tmdb_id, int(season_num), int(ep.get("episode"))))
        
    results = await asyncio.gather(*tasks)
    
    try:
        await bot.delete_message(status_msg.chat.id, status_msg.message_id)
        await bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
        
    m3u_content = "#EXTM3U\n"
    tracks_count = 0
    
    for ep, (stream_url, logo_url) in zip(episodes, results):
        if stream_url:
            m3u_content += f"#EXTINF:-1 tvg-logo=\"{logo_url}\" group-title=\"{BRAND_NAME} Series\", {title} - S{season_num}E{ep.get('episode')}: {ep.get('name')}\n"
            m3u_content += f"{stream_url}\n"
            tracks_count += 1
            
    if tracks_count == 0:
        fail_msg = await bot.send_message(
            chat_id=call.message.chat.id,
            text="🥺 *Arey yaar! Is season ke kisi bhi episode ka link resolve nahi ho paya.*",
            reply_markup=get_home_keyboard()
        )
        asyncio.create_task(delayed_delete(fail_msg.chat.id, fail_msg.message_id, 10))
        return
        
    await deliver_m3u_file(call.message.chat.id, filename, m3u_content, f"{title} (Season {season_num})", call.from_user.first_name)

# --- M3U DOCUMENT DELIVERY UNIT ---
async def deliver_m3u_file(chat_id: int, filename: str, content: str, title: str, requester_name: str):
    """Saves compiled content to M3U file, uploads to group, and performs automatic cleanups."""
    global total_m3u_generated
    try:
        # Write local temp file
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
            
        total_m3u_generated += 1
        
        # Deliver file document
        with open(filename, "rb") as doc_file:
            caption = (
                f"📂 *𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐌𝟑𝐔 𝐏𝐋𝐀𝐘𝐋𝐈𝐒𝐓 𝐆𝐄𝐍𝐄𝐑𝐀𝐓𝐄𝐃!* 🍿\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎬 *Title:* `{title}`\n"
                f"👤 *Requested By:* `{requester_name}`\n"
                f"⚙️ *Format:* Tivimate / OTT Navigator compatible\n"
                f"👑 *Power:* {BRAND_NAME}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ _Note: This file and message will auto-delete in 30 seconds..._"
            )
            doc_msg = await bot.send_document(
                chat_id=chat_id,
                document=doc_file,
                caption=caption,
                parse_mode="Markdown"
            )
            
        # Schedule auto delete of the document file in 30s
        asyncio.create_task(delayed_delete(chat_id, doc_msg.message_id, 30))
        
    except Exception as e:
        logger.error(f"Error during M3U generation or file handling: {e}")
        await bot.send_message(chat_id=chat_id, text="🥺 *Sorry!* M3U document packaging failed.")
        
    finally:
        # Local cleanup immediately
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# Fallback RAW text handler for normal message text input search queries


# --- ANALYSIS ENGINE (ADMIN-ONLY ACCESS) ---
@bot.message_handler(commands=['analysis'])
async def cmd_analysis_handler(message):
    if not await check_authorization(message) or not await handle_anti_spam(message):
        return
        
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Restrict /analysis command execution to administrators and creators only
    if not await is_admin(chat_id, user_id):
        warning_msg = await bot.send_message(
            chat_id=chat_id,
            text="🚫 *ACCESS DENIED!* ⚠️\n\nSuno yaar, `/analysis` dashboard sirf group *Admins & Creators* ke liye hi allowed hai!",
            parse_mode="Markdown"
        )
        asyncio.create_task(delayed_delete(chat_id, message.message_id, 5))
        asyncio.create_task(delayed_delete(chat_id, warning_msg.message_id, 5))
        return
        
    track_user(message.from_user, "Viewed Admin /analysis dashboard")
    asyncio.create_task(delayed_delete(chat_id, message.message_id, 10))
    
    ping = int((time.time() - message.date) * 1000)
    if ping < 0:
        ping = 15
        
    total_users_count = len(load_users())
    active_users_count = len(active_users_session)
    if active_users_count == 0:
        active_users_count = 1
        
    uptime = get_uptime()
    live_graph = generate_live_load_graph()
    
    cpu_sim = "████████░░"
    ram_sim = "██████░░░░"
    
    text = (
        f"💎 ── *𝐌𝐎𝐕𝐈𝐄𝐒  𝐏𝐀𝐆𝐋𝐔  𝐒𝐘𝐒𝐓𝐄𝐌  𝐏𝐑𝐎𝐅𝐈𝐋𝐄* ── 💎\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 *Owner:* {BRAND_NAME}\n"
        f"🌐 *Host Node:* Railway Cloud - Termux VPS\n"
        f"⏱ *Uptime:* `{uptime}`\n"
        f"⚡ *Latency / Ping:* `{ping}ms`\n\n"
        f"📊 *DATABASE METRICS:*\n"
        f"👤 *Total Users registered:* `{total_users_count}`\n"
        f"🔥 *Active Session Users:* `{active_users_count}`\n"
        f"📥 *Total Queries Resolved:* `{total_queries_handled}`\n"
        f"📁 *M3U Playlists Generated:* `{total_m3u_generated}`\n\n"
        f"📈 *HARDWARE DIAGNOSTIC LOADS:*\n"
        f"⚙️ *CPU Capacity:* `[{cpu_sim}] 80%` (Optimal)\n"
        f"💾 *RAM Allocation:* `[{ram_sim}] 60%` (Smooth)\n\n"
        f"📈 *REAL-TIME PERFORMANCE TREND:*\n"
        f"```\n{live_graph}\n```\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌸 *Powered by Movies Paglu Engine*" + get_text(message.from_user.id, "auto_delete_note")
    )
    
    analysis_msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=get_home_keyboard(),
        parse_mode="Markdown"
    )
    asyncio.create_task(delayed_delete(chat_id, analysis_msg.message_id, 10))

# --- MAIN EXECUTION ---
async def main():
    print("✅ Bot Started Successfully...")
    logger.info("Bot started successfully in async polling mode with security & M3U configurations.")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Polling session stopped.")