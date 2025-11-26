import os
import logging
import json
import asyncio
from datetime import time
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from io import BytesIO

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq

from PIL import Image
import pytesseract

# ព្យាយាម Import keep_alive
try:
    from keep_alive import keep_alive
except ImportError:
    keep_alive = None

# ================= 1. CONFIGURATION =================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
USERS_FILE = "users.json"

# USER_MODES: {chat_id: 'auto' | 'learner' | 'foreigner'}
USER_MODES: dict[int, str] = {}
# USER_STATS: {chat_id: message_count}
USER_STATS: dict[int, int] = {}

# ----- Logging to console + file -----
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(console_handler)

# file handler (rotate ~1MB, keep 3 backups)
file_handler = RotatingFileHandler(
    "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    client = None
    logger.warning("⚠️ GROQ_API_KEY is missing! AI responses will not work.")

# ================= 2. PROMPTS =================

PROMPT_KHMER_LEARNER = """
You are an expert Multi-Language Tutor (English & Chinese) for Khmer speakers.

YOUR TASK:
1. Analyze the user's input.
2. Provide the ENGLISH translation/correction with Khmer Phonetics.
3. Provide the CHINESE translation with PINYIN and Khmer Phonetics.
4. Provide the KHMER meaning.
5. **CRITICAL:** ALWAYS provide a Usage Example in ALL 3 languages, INCLUDING PINYIN for Chinese.

OUTPUT FORMAT:
--------------------------------
🇺🇸 **English:** [English Sentence]
🗣️ **អានថា:** [Sound of English in Khmer Script]
--------------------------------
🇨🇳 **Chinese:** [Chinese Characters]
🎼 **Pinyin:** [Pinyin]
🗣️ **អានថា:** [Sound of Chinese in Khmer Script]
--------------------------------
🇰🇭 **ប្រែថា:** [Khmer Meaning]
--------------------------------
📝 **ឧទាហរណ៍ (Example):**
🇺🇸 [English Example Sentence]
🇨🇳 [Chinese Example Sentence]
🎼 [Pinyin for Example]
🇰🇭 [Khmer Example Sentence]
--------------------------------
"""

PROMPT_FOREIGNER = """
You are a Khmer Language & Cultural Guide for Foreigners.
YOUR TASK:
1. Translate English/Chinese input into **Standard Polite Khmer**.
2. Provide **Romanized Phonetics**.
3. Provide a Cultural Tip.

OUTPUT FORMAT:
--------------------------------
🇰🇭 **Khmer Script:** [Writing in Khmer]
🗣️ **Say:** [Romanized Phonetics]
📖 **Meaning:** [Literal meaning]
--------------------------------
💡 **Tip:** [Cultural context]
"""

# ================= 3. HELPER FUNCTIONS =================

def load_users() -> set[int]:
    if not os.path.exists(USERS_FILE):
        return set()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        try:
            return set(json.load(f))
        except Exception as e:
            logger.warning(f"Failed to load users file: {e}")
            return set()


def save_user_to_file(chat_id: int) -> None:
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        try:
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(users), f)
        except Exception as e:
            logger.error(f"Failed to save users file: {e}")


def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳"), KeyboardButton("🇺🇸 -> 🇰🇭 (Foreigner)")],
        [KeyboardButton("📩 Feedback"), KeyboardButton("❓ Help/ជំនួយ")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ----- Simple language-based mode detection -----

def detect_mode_from_text(text: str) -> str:
    """
    Heuristic:
    - Only Khmer characters -> learner
    - Latin/Chinese but no Khmer -> foreigner
    - Mixed -> default learner
    """
    has_khmer = any("\u1780" <= ch <= "\u17FF" for ch in text)
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    has_latin = any("a" <= ch.lower() <= "z" for ch in text if ch.isalpha())

    if has_khmer and not (has_latin or has_cjk):
        mode = "learner"
    elif (has_latin or has_cjk) and not has_khmer:
        mode = "foreigner"
    else:
        mode = "learner"

    logger.info(f"Auto-detected mode from text='{text[:30]}...': {mode}")
    return mode


async def get_ai_response(chat_id: int, user_text: str) -> str:
    if not client:
        return "⚠️ Server Error: Missing API Key."

    mode = USER_MODES.get(chat_id, "auto")

    # Auto-detect mode only if user hasn't chosen explicitly yet
    if mode == "auto":
        mode = detect_mode_from_text(user_text)
        USER_MODES[chat_id] = mode  # remember for next time

    system_prompt = PROMPT_FOREIGNER if mode == "foreigner" else PROMPT_KHMER_LEARNER
    logger.info(f"Using mode='{mode}' for chat_id={chat_id}")

    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            model=GROQ_MODEL_CHAT,
            temperature=0.3,
            max_tokens=1500,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI Chat Error: {e}")
        return "⚠️ Error connecting to AI."


async def send_long_message(update: Update, text: str) -> None:
    """
    Telegram មានលីមីតប្រវែងសារ ~4096 characters
    ដូច្នេះបំបែកជាបន្ទាត់តូចៗ មុនផ្ញើ
    """
    if not text:
        return

    max_len = 4000
    if len(text) <= max_len:
        await update.message.reply_text(text)
        return

    for i in range(0, len(text), max_len):
        chunk = text[i : i + max_len]
        await update.message.reply_text(chunk)

# ================= 4. SCHEDULING ALERT =================

async def send_scheduled_alert(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends automatic messages to all users"""
    message = context.job.data
    users = load_users()
    logger.info(f"⏰ Auto-Sending Alert to {len(users)} users: {message!r}")
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
        except Exception as e:
            logger.warning(f"Failed to send scheduled alert to {uid}: {e}")

# ================= 5. HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user_to_file(chat_id)

    # default first-time mode = auto (detect from message later)
    if chat_id not in USER_MODES:
        USER_MODES[chat_id] = "auto"

    msg = (
        f"👋 **សួស្តី {user.first_name}! សូមស្វាគមន៍មកកាន់ AI Language Tutor!**\n\n"
        "👨‍🏫 **ខ្ញុំអាចជួយអ្នករៀនភាសា អង់គ្លេស និង ចិន។**\n\n"
        "📚 **របៀបប្រើប្រាស់:**\n"
        "1️⃣ **🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳 (សិស្សរៀនភាសា)**\n"
        "• វាយជាខ្មែរ ឬអង់គ្លេស ខ្ញុំនឹងបកប្រែជា **អង់គ្លេស និង ចិន (មាន Pinyin)** ព្រមទាំងប្រាប់របៀបអាន។\n\n"
        "2️⃣ **🇺🇸 -> 🇰🇭 (Foreigner)**\n"
        "• For foreigners learning Khmer.\n\n"
        "📌 Mode ដំបូងនឹងកំណត់ស្វ័យប្រវត្តិតាមភាសាសារ​អ្នក។\n"
        "📷 អាចផ្ញើ screenshot/រូបភាព មានអក្សរ ដើម្បីបកប្រែបានផងដែរ។\n"
        "👇 **សូមចុចប៊ូតុងខាងក្រោម ដើម្បីចាប់ផ្តើម!**"
    )

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "🆘 **ជំនួយ ប្រើ Bot**\n\n"
        "• Mode ដំបូង៖ Auto-detect តាមភាសាសារ។\n\n"
        "1️⃣ Text Chat:\n"
        "   • សរសេរ ខ្មែរ / English / Chinese មក\n"
        "   • Bot នឹងបកប្រែ តាម mode (learner / foreigner).\n\n"
        "2️⃣ Screenshot / Image:\n"
        "   • ផ្ញើរូបភាព/screenshot ដែលមានអក្សរ\n"
        "   • Bot នឹងអានអក្សរ (OCR) ហើយបកប្រែដូចសារ text។\n\n"
        "3️⃣ ផ្ញើមតិយោបល់:\n"
        "   • `/feedback សារ​របស់​អ្នក`\n\n"
        "4️⃣ ប្ដូរ Mode ដោយ command:\n"
        "   • `/mode learner`  – Khmer Learner\n"
        "   • `/mode foreigner` – Foreigner\n"
        "   • `/mode auto`      – Auto-detect\n\n"
        "👇 ប្រើ /menu ដើម្បីបង្ហាញប៊ូតុងម្ដងទៀត។"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "ℹ️ **About AI Language Tutor Bot**\n\n"
        "• ជួយសិស្សខ្មែរ រៀន អង់គ្លេស និង ចិន (មាន Pinyin និងសូរ​អានជាខ្មែរ).\n"
        "• ជួយ Foreigner បកប្រែ English/Chinese ទៅ Khmer (script + romanization + tips).\n"
        "• Auto-detect mode + Screenshot OCR translate.\n\n"
        "Commands សំខាន់ៗ:\n"
        "• `/start`  – ចាប់ផ្តើម\n"
        "• `/help`   – របៀបប្រើ\n"
        "• `/menu`   – ប៊ូតុង\n"
        "• `/mode`   – ប្ដូរ mode\n"
        "• `/feedback` – មតិយោបល់\n"
        "• `/stats` – (Admin) ស្ថិតិ bot\n\n"
        "🙏 អរគុណសម្រាប់ការប្រើប្រាស់!"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📋 ម៉ឺនុយត្រូវបានបង្ហាញឡើងវិញ។ សូមជ្រើសរើស Mode ឬ Function ខាងក្រោម 🎛️",
        reply_markup=get_main_keyboard(),
    )


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text(
            "សូមប្រើ៖ `/feedback សារ​របស់​អ្នក`", parse_mode=ParseMode.MARKDOWN
        )
        return

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=int(ADMIN_ID), text=f"📩 Feedback: {msg}"
            )
            await update.message.reply_text("✅ Feedback sent.")
        except Exception as e:
            logger.error(f"Failed to send feedback to ADMIN: {e}")
            await update.message.reply_text("⚠️ មិនអាចផ្ញើ Feedback ទៅ Admin បានទេ។")
    else:
        await update.message.reply_text("⚠️ ADMIN_ID មិនត្រូវបានកំណត់ទេ។")


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not context.args:
        current = USER_MODES.get(chat_id, "auto")
        txt = (
            "🔧 **Current Mode:** `{}`\n\n"
            "ប្រើ:\n"
            "• `/mode learner`   – 🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳 (Khmer Learner)\n"
            "• `/mode foreigner` – 🇺🇸 -> 🇰🇭 (Foreigner)\n"
            "• `/mode auto`      – Auto-detect\n"
        ).format(current)
        await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)
        return

    arg = context.args[0].lower()
    if arg in ["learner", "khmer", "student"]:
        USER_MODES[chat_id] = "learner"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Khmer Learner**\nសរសេរខ្មែរ/អង់គ្លេស មកបាន!",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif arg in ["foreigner", "en", "eng", "english"]:
        USER_MODES[chat_id] = "foreigner"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Foreigner (English/Chinese -> Khmer)**",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif arg in ["auto", "detect"]:
        USER_MODES[chat_id] = "auto"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Auto-detect**\nខ្ញុំនឹងកំណត់ learner/foreigner ស្វ័យប្រវត្តិតាមភាសាសារ!",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "⚠️ Mode មិនស្គាល់។\nប្រើ: `/mode learner`, `/mode foreigner` ឬ `/mode auto`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID):
        return

    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text(
            "សូមវាយសារ៖ `/broadcast សារ​ត្រូវ​ផ្ញើ`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    users = load_users()
    sent = 0
    failed = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
            sent += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to send broadcast to {uid}: {e}")

    await update.message.reply_text(
        f"✅ Broadcast sent to {sent} users. Failed: {failed}."
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID):
        return

    users = load_users()
    total_users = len(users)
    total_msgs = sum(USER_STATS.values()) if USER_STATS else 0

    mode_counts = {"auto": 0, "learner": 0, "foreigner": 0}
    for m in USER_MODES.values():
        if m in mode_counts:
            mode_counts[m] += 1

    msg = (
        "📊 **Bot Stats**\n\n"
        f"• Registered users (file): `{total_users}`\n"
        f"• Active users in memory: `{len(USER_MODES)}`\n"
        f"• Total messages this run: `{total_msgs}`\n\n"
        "Modes in memory:\n"
        f"• auto: `{mode_counts['auto']}`\n"
        f"• learner: `{mode_counts['learner']}`\n"
        f"• foreigner: `{mode_counts['foreigner']}`\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# ----- NEW: handle photo (screenshot) with OCR -----

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id
    USER_STATS[chat_id] = USER_STATS.get(chat_id, 0) + 1

    photo = update.message.photo[-1]  # biggest size
    try:
        file = await photo.get_file()
        bio = BytesIO()
        await file.download_to_memory(bio)
        bio.seek(0)
        image = Image.open(bio)
    except Exception as e:
        logger.error(f"Failed to download/open image: {e}")
        await update.message.reply_text(
            "⚠️ មិនអាចទាញយក ឬបើករូបភាពបានទេ។ សូមសាកល្បងម្ដងទៀត។"
        )
        return

    try:
        # អាចកំណត់ lang ដូចជា 'eng+chi_sim' បើ install models រួច
        ocr_text = pytesseract.image_to_string(image)
        logger.info(f"OCR text from image (first 100 chars): {ocr_text[:100]!r}")
    except Exception as e:
        logger.error(f"OCR error: {e}")
        await update.message.reply_text(
            "⚠️ OCR Error: មិនអាចអានអក្សរពីរូបភាពបានទេ។"
        )
        return

    if not ocr_text or not ocr_text.strip():
        await update.message.reply_text(
            "⚠️ មិនរកឃើញអក្សរពីក្នុងរូបភាពទេ។ សូមប្រើរូបភាពដែលអក្សរច្បាស់ជាងនេះ។"
        )
        return

    save_user_to_file(chat_id)
    if chat_id not in USER_MODES:
        USER_MODES[chat_id] = "auto"

    await context.bot.send_chat_action(
        chat_id=chat_id, action=ChatAction.TYPING
    )

    reply = await get_ai_response(chat_id, ocr_text.strip())
    if reply is None:
        reply = "⚠️ No response from AI."

    header = "📷 **បកប្រែពីរូបភាព (Screenshot Translation):**\n\n"
    await send_long_message(update, header + str(reply))

# ----- Handle normal text -----

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text
    chat_id = update.effective_chat.id

    USER_STATS[chat_id] = USER_STATS.get(chat_id, 0) + 1
    logger.info(
        f"Message from {chat_id}: {text[:50]}... (count={USER_STATS[chat_id]})"
    )

    if chat_id not in USER_MODES:
        USER_MODES[chat_id] = "auto"

    if text == "🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳":
        USER_MODES[chat_id] = "learner"
        await update.message.reply_text(
            "✅ **Mode: Khmer Learner**\nសរសេរមកបាន! ខ្ញុំនឹងចេញទាំង អង់គ្លេស និង ចិន។",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif text == "🇺🇸 -> 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = "foreigner"
        await update.message.reply_text(
            "✅ **Mode: Foreigner Standard**",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif text == "📩 Feedback":
        await update.message.reply_text(
            "Type: `/feedback [msg]`", parse_mode=ParseMode.MARKDOWN
        )
    elif text == "❓ Help/ជំនួយ":
        await help_command(update, context)
    else:
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(
            chat_id=chat_id, action=ChatAction.TYPING
        )
        reply = await get_ai_response(chat_id, text)

        if reply is None:
            reply = "⚠️ No response from AI."
        else:
            reply = str(reply)

        await send_long_message(update, reply)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cmd = update.message.text
    msg = (
        f"⚠️ Command `{cmd}` មិនស្គាល់ទេ។\n\n"
        "សូមប្រើ:\n"
        "• `/help`  – មើលរបៀបប្រើ\n"
        "• `/menu`  – បង្ហាញប៊ូតុង\n"
        "• `/mode`  – ប្ដូរ mode\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# ================= 6. MAIN EXECUTION =================

if __name__ == "__main__":
    if keep_alive:
        keep_alive()

    if not TELEGRAM_TOKEN:
        logger.error("❌ Error: TELEGRAM_TOKEN missing.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

        # Commands
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("about", about_command))
        app.add_handler(CommandHandler("menu", menu_command))
        app.add_handler(CommandHandler("mode", mode_command))
        app.add_handler(CommandHandler("feedback", feedback_command))
        app.add_handler(CommandHandler("broadcast", broadcast))
        app.add_handler(CommandHandler("stats", stats_command))

        # Photos (screenshots)
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

        # Text messages (non-command)
        app.add_handler(
            MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
        )

        # Unknown commands (must be AFTER all CommandHandlers)
        app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

        # Job queue (scheduled messages)
        jq = app.job_queue
        jq.run_daily(
            send_scheduled_alert,
            time=time(1, 0),
            data="☀️ អរុណសួស្តី! Good Morning!",
            name="morning",
        )
        jq.run_daily(
            send_scheduled_alert,
            time=time(6, 0),
            data="☕ ទិវាសួស្តី! Good Afternoon!",
            name="afternoon",
        )
        jq.run_daily(
            send_scheduled_alert,
            time=time(13, 0),
            data="🌙 រាត្រីសួស្តី! Good Evening!",
            name="evening",
        )

        logger.info("✅ Bot is running with Scheduler...")
        app.run_polling(drop_pending_updates=True)
