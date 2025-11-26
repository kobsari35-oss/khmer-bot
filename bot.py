import os
import logging
import json
import asyncio
import base64
from datetime import time
from io import BytesIO
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from groq import Groq

# ព្យាយាម Import keep_alive (optional for uptime ping)
try:
    from keep_alive import keep_alive
except ImportError:
    keep_alive = None

# =============== 1. CONFIGURATION =================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
GROQ_MODEL_VISION = "meta-llama/llama-4-scout-17b-16e-instruct"

USERS_FILE = "users.json"

# USER_MODES: {chat_id: 'auto' | 'learner' | 'foreigner'}
USER_MODES: dict[int, str] = {}
# USER_STATS: {chat_id: message_count}
USER_STATS: dict[int, int] = {}

# ----- Logging to console + file -----
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(console_handler)

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

# =============== 2. PROMPTS =======================

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

# --- Grammar prompts ---

PROMPT_KM_GRAMMAR = """
You are an expert Khmer language teacher.

Task:
- Correct the grammar, spelling, spacing and word choice of the Khmer sentence.
- Keep the meaning as close as possible.
- Explain the main corrections in simple Khmer.

Output format (Khmer language):
--------------------------------
✍️ ប្រយោគដើម:
[Original Khmer sentence]

✅ ប្រយោគកែត្រឹមត្រូវ:
[Corrected Khmer sentence]

📝 ពន្យល់កំហុស:
- [Short explanation point 1]
- [Short explanation point 2]
--------------------------------
"""

PROMPT_EN_GRAMMAR = """
You are an expert English writing tutor.

Task:
- Correct grammar, spelling, word order, and style.
- Keep the original meaning.
- Give a brief explanation of the mistakes in simple English.

Output format:
--------------------------------
✍️ Original:
[Original sentence]

✅ Corrected:
[Corrected sentence]

📝 Notes:
- [Short explanation point 1]
- [Short explanation point 2]
--------------------------------
"""

PROMPT_CN_GRAMMAR = """
You are an expert Mandarin Chinese teacher.

Task:
- Correct grammar, word choice, and word order for Mandarin Chinese.
- Use Simplified Chinese.
- Provide Pinyin for the corrected sentence.
- Explain the main corrections in Khmer (for Khmer students).

Output format:
--------------------------------
✍️ 句子原文 (Original):
[Original Chinese sentence]

✅ 改正后的句子 (Corrected):
[Corrected sentence in Chinese]

🎼 Pinyin:
[Pinyin for corrected sentence]

📝 ពន្យល់កំហុស (Khmer explanation):
- [Short explanation point 1]
- [Short explanation point 2]
--------------------------------
"""

# =============== 3. HELPER FUNCTIONS ==============


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


def detect_mode_from_text(text: str) -> str:
    """Simple heuristic: Khmer only -> learner, Latin/Chinese only -> foreigner, mixed -> learner."""
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


async def chat_with_system_prompt(system_prompt: str, user_text: str) -> str:
    """Generic helper to call Groq with a custom system prompt."""
    if not client:
        return "⚠️ Server Error: Missing API Key."

    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL_CHAT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"chat_with_system_prompt error: {e}")
        return "⚠️ Error connecting to AI."


async def get_ai_response(chat_id: int, user_text: str) -> str:
    """Main translation / tutor logic using modes."""
    mode = USER_MODES.get(chat_id, "auto")

    # Auto-detect mode only if user hasn't chosen explicitly yet
    if mode == "auto":
        mode = detect_mode_from_text(user_text)
        USER_MODES[chat_id] = mode  # remember for next time

    system_prompt = PROMPT_FOREIGNER if mode == "foreigner" else PROMPT_KHMER_LEARNER
    logger.info(f"Using mode='{mode}' for chat_id={chat_id}")
    return await chat_with_system_prompt(system_prompt, user_text)


async def send_long_message(update: Update, text: str) -> None:
    """Split long messages to respect Telegram 4096-char limit."""
    if not text:
        return

    max_len = 4000
    if len(text) <= max_len:
        await update.message.reply_text(text)
        return

    for i in range(0, len(text), max_len):
        chunk = text[i : i + max_len]
        await update.message.reply_text(chunk)


# =============== 4. SCHEDULING ALERT ==============


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


# =============== 5. COMMAND HANDLERS ==============


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user_to_file(chat_id)

    if chat_id not in USER_MODES:
        USER_MODES[chat_id] = "auto"

    msg = (
        f"👋 **សួស្តី {user.first_name}! សូមស្វាគមន៍មកកាន់ AI Language Tutor!**\n\n"
        "👨‍🏫 **ខ្ញុំអាចជួយអ្នករៀនភាសា អង់គ្លេស និង ចិន។**\n\n"
        "📚 **មុខងារសំខាន់ៗ:**\n"
        "• 🇰🇭 -> 🇺🇸🇨🇳  Khmer Learner Mode\n"
        "• 🇺🇸/🇨🇳 -> 🇰🇭 Foreigner Mode\n"
        "• 🖼 Screenshot OCR Translate\n"
        "• ✏️ Grammar Correction: `/kmgrammar`, `/enggrammar`, `/cngrammar`\n\n"
        "📌 Mode ដំបូងកំណត់ស្វ័យប្រវត្តិតាមភាសាសារ។\n"
        "👇 **សូមចុចប៊ូតុងខាងក្រោម ដើម្បីចាប់ផ្តើម!**"
    )

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "🆘 **ជំនួយ ប្រើ Bot**\n\n"
        "1️⃣ Translation Modes\n"
        "   • `/mode learner`   – 🇰🇭 -> 🇺🇸🇨🇳 (Khmer Learner)\n"
        "   • `/mode foreigner` – 🇺🇸/🇨🇳 -> 🇰🇭 (Foreigner)\n"
        "   • `/mode auto`      – Auto-detect\n\n"
        "2️⃣ Screenshot / Image OCR\n"
        "   • ផ្ញើរូបភាព/screenshot មានអក្សរ → Bot អានអក្សរ ហើយបកប្រែ\n\n"
        "3️⃣ Grammar Correction\n"
        "   • `/kmgrammar ប្រ្យោគខ្មែរ...`  – ពិនិត្យ & កែភាសាខ្មែរ\n"
        "   • `/enggrammar English sentence...` – ពិនិត្យ & កែភាសាអង់គ្លេស\n"
        "   • `/cngrammar 中文句子...` – ពិនិត្យ & កែភាសាចិន (មាន Pinyin + ពន្យល់ខ្មែរ)\n\n"
        "4️⃣ ផ្ញើមតិយោបល់\n"
        "   • `/feedback សារ​របស់​អ្នក`\n\n"
        "👇 ប្រើ /menu ដើម្បីបង្ហាញប៊ូតុងម្ដងទៀត។"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "ℹ️ **About AI Language Tutor Bot**\n\n"
        "• Khmer ⇄ English ⇄ Chinese translation & tutoring\n"
        "• Screenshot OCR with Groq Vision\n"
        "• Grammar correction:\n"
        "   – Khmer (/kmgrammar)\n"
        "   – English (/enggrammar)\n"
        "   – Chinese (/cngrammar)\n"
        "• Auto-detect learning mode\n\n"
        "Commands សំខាន់ៗ:\n"
        "• `/start`  – ចាប់ផ្តើម\n"
        "• `/help`   – របៀបប្រើ\n"
        "• `/menu`   – ប៊ូតុង\n"
        "• `/mode`   – ប្ដូរ mode\n"
        "• `/kmgrammar`, `/enggrammar`, `/cngrammar`\n"
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
            "• `/mode learner`   – 🇰🇭 -> 🇺🇸🇨🇳 (Khmer Learner)\n"
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


# =============== 6. GRAMMAR COMMANDS ===============

async def kmgrammar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "ប្រើ៖ `/kmgrammar ប្រ្យោគភាសាខ្មែរ​របស់​អ្នក`\n\n"
            "ឧ. `/kmgrammar ថ្ងៃនេះខ្ញុំទៅរៀនសាលា៉`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("✏️ កំពុងពិនិត្យវេយ្យាករណ៍ភាសាខ្មែរ...")
    reply = await chat_with_system_prompt(PROMPT_KM_GRAMMAR, text)
    await send_long_message(update, reply)


async def enggrammar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "Use: `/enggrammar your English sentence`\n\n"
            "e.g. `/enggrammar She go to market yesterday.`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("✏️ Checking English grammar...")
    reply = await chat_with_system_prompt(PROMPT_EN_GRAMMAR, text)
    await send_long_message(update, reply)


async def cngrammar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "使用: `/cngrammar 你的中文句子`\n\n"
            "例如: `/cngrammar 我昨天去市场买东西了`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("✏️ 正在检查中文语法 / កំពុងពិនិត្យភាសាចិន...")
    reply = await chat_with_system_prompt(PROMPT_CN_GRAMMAR, text)
    await send_long_message(update, reply)


# =============== 7. PHOTO HANDLER (VISION OCR) =====


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Use Groq Vision model to OCR the image, then translate like normal text."""
    if not client:
        await update.message.reply_text("⚠️ Server Error: Missing API Key.")
        return

    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id
    USER_STATS[chat_id] = USER_STATS.get(chat_id, 0) + 1

    # ---- Download image ----
    photo = update.message.photo[-1]  # largest size
    try:
        file = await photo.get_file()
        bio = BytesIO()
        await file.download_to_memory(bio)
        image_bytes = bio.getvalue()
    except Exception as e:
        logger.error(f"Failed to download image: {e}")
        await update.message.reply_text(
            "⚠️ មិនអាចទាញយករូបភាពបានទេ។ សូមសាកល្បងម្ដងទៀត។"
        )
        return

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    await update.message.reply_text("🖼️ កំពុងអានអក្សរពីរូបភាព...")

    # ---- Groq Vision OCR ----
    try:
        vision_resp = client.chat.completions.create(
            model=GROQ_MODEL_VISION,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract ALL readable text from this image. "
                                    "Return plain text only, no explanation.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_image}"
                            },
                        },
                    ],
                }
            ],
        )

        ocr_text = vision_resp.choices[0].message.content or ""
        ocr_text = str(ocr_text).strip()
    except Exception as e:
        logger.error(f"Groq Vision OCR error: {e}")
        await update.message.reply_text(
            "⚠️ OCR Error: មិនអាចអានអក្សរពីរូបភាពបានទេ។"
        )
        return

    if not ocr_text:
        await update.message.reply_text(
            "⚠️ មិនរកឃើញអក្សរពីក្នុងរូបភាពទេ។ សូមប្រើរូបភាពដែលអក្សរច្បាស់ជាងនេះ។"
        )
        return

    save_user_to_file(chat_id)
    if chat_id not in USER_MODES:
        USER_MODES[chat_id] = "auto"

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    reply = await get_ai_response(chat_id, ocr_text)
    if reply is None:
        reply = "⚠️ No response from AI."

    header = "📷 **បកប្រែពីរូបភាព (Screenshot Translation):**\n\n"
    await send_long_message(update, header + str(reply))


# =============== 8. TEXT HANDLER ===================


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
        "• `/kmgrammar`, `/enggrammar`, `/cngrammar` – Grammar correction\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# =============== 9. MAIN ===========================

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

        # Grammar commands
        app.add_handler(CommandHandler("kmgrammar", kmgrammar_command))
        app.add_handler(CommandHandler("enggrammar", enggrammar_command))
        app.add_handler(CommandHandler("cngrammar", cngrammar_command))

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
