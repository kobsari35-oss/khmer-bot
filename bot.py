#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Language Tutor Telegram Bot
Khmer ⇄ English ⇄ Chinese + Korean + Japanese + Filipino
+ OCR + Grammar Tools + Extra Features

Author: Kobsari (refactored + extended)
"""

import asyncio
import base64
import json
import logging
import os
from datetime import time as dt_time
from logging.handlers import RotatingFileHandler
from typing import Dict, Set, Optional

from dotenv import load_dotenv
from groq import Groq
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Optional uptime ping (Replit / Render, etc.)
try:
    from keep_alive import keep_alive
except ImportError:  # pragma: no cover
    keep_alive = None

# ==================================================
# 1. CONFIGURATION & GLOBALS
# ==================================================

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID_RAW = os.getenv("ADMIN_ID")

try:
    ADMIN_ID: Optional[int] = int(ADMIN_ID_RAW) if ADMIN_ID_RAW else None
except ValueError:
    ADMIN_ID = None

GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
GROQ_MODEL_VISION = "meta-llama/llama-4-scout-17b-16e-instruct"

USERS_FILE = "users.json"

# USER_MODES: {chat_id: 'auto' | 'learner' | 'foreigner' | 'korean' | 'japanese' | 'filipino'}
USER_MODES: Dict[int, str] = {}
# USER_STATS: {chat_id: message_count}
USER_STATS: Dict[int, int] = {}

# ==================================================
# 2. LOGGING
# ==================================================

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

# Groq client
if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    client = None
    logger.warning("⚠️ GROQ_API_KEY is missing! AI responses will not work.")

# ==================================================
# 3. SYSTEM PROMPTS
# ==================================================

PROMPT_KHMER_LEARNER = """
You are an expert Multi-Language Tutor (English & Chinese) for Khmer speakers.

YOUR TASK:
1. Analyze the user's input.
2. Provide the ENGLISH translation/correction.
3. Provide the CHINESE translation with PINYIN.
4. Provide the KHMER meaning.
5. ALWAYS provide a Usage Example in ALL 3 languages, INCLUDING PINYIN for Chinese.

OUTPUT FORMAT:
--------------------------------
🇺🇸 **English:** [English Sentence]
--------------------------------
🇨🇳 **Chinese:** [Chinese Characters]
🎼 **Pinyin:** [Pinyin]
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

TASK:
1. Translate English/Chinese input into Standard Polite Khmer.
2. Provide Romanized Phonetics.
3. Provide a Cultural Tip.

OUTPUT FORMAT:
--------------------------------
🇰🇭 **Khmer Script:** [Writing in Khmer]
🗣️ **Say:** [Romanized Phonetics]
📖 **Meaning:** [Literal meaning]
--------------------------------
💡 **Tip:** [Cultural context]
"""

PROMPT_KOREAN_LEARNER = """
You are a Korean language tutor for Khmer speakers.

TASK:
1. Translate or correct the sentence in Korean.
2. Provide Korean in Hangul and Romanization.
3. Explain the meaning in Khmer.
4. Give 1–2 example sentences.

OUTPUT FORMAT:
--------------------------------
🇰🇷 **Korean:** [Hangul sentence]
🗣️ **Romanization:** [Romanized Korean]
🇰🇭 **ប្រែថា:** [Khmer meaning]
--------------------------------
📝 **ឧទាហរណ៍ (Example):**
🇰🇷 [Example Korean sentence]
🗣️ [Romanization]
🇰🇭 [Khmer example sentence]
--------------------------------
"""

PROMPT_JAPANESE_LEARNER = """
You are a Japanese language tutor for Khmer speakers.

TASK:
1. Translate or correct the sentence in Japanese.
2. Provide Romaji (Latin script).
3. Explain the meaning in Khmer.
4. Give 1–2 example sentences.

OUTPUT FORMAT:
--------------------------------
🇯🇵 **Japanese:** [Japanese sentence]
🗣️ **Romaji:** [Romaji sentence]
🇰🇭 **ប្រែថា:** [Khmer meaning]
--------------------------------
📝 **ឧទាហរណ៍ (Example):**
🇯🇵 [Example Japanese sentence]
🗣️ [Romaji]
🇰🇭 [Khmer example sentence]
--------------------------------
"""

PROMPT_FILIPINO_LEARNER = """
You are a Filipino (Tagalog) language tutor for Khmer speakers.

TASK:
1. Translate or correct the sentence in Filipino.
2. Provide a clear, natural Filipino sentence.
3. Explain the meaning in Khmer.
4. Give 1–2 example sentences.

OUTPUT FORMAT:
--------------------------------
🇵🇭 **Filipino:** [Filipino sentence]
🇰🇭 **ប្រែថា:** [Khmer meaning]
--------------------------------
📝 **ឧទាហរណ៍ (Example):**
🇵🇭 [Example Filipino sentence]
🇰🇭 [Khmer example sentence]
--------------------------------
"""

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
- Correct grammar, word choice, and word order for Mandarin Chinese (Simplified).
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

PROMPT_EXPLAIN = """
You are a friendly multilingual language tutor for a Khmer-speaking student.

Task:
1. Detect the language of the input sentence (Khmer, English, or Chinese).
2. Explain the full meaning in simple Khmer.
3. Highlight important vocabulary with short Khmer explanations (as bullet points).
4. Give 1–2 extra example sentences in the same language as the original, each with a Khmer translation.

Output format (Khmer UI):
--------------------------------
✍️ ប្រយោគដើម:
[Original sentence]

🇰🇭 ពន្យល់ជាភាសាខ្មែរ:
[Explanation in simple Khmer, 2–5 short sentences]

📚 ពាក្យសំខាន់ៗ:
- [word 1] – [Khmer meaning]
- [word 2] – [Khmer meaning]

📝 ឧទាហរណ៍បន្ថែម:
[Example sentence 1] → [Khmer translation]
[Example sentence 2] → [Khmer translation]
--------------------------------
"""

# ==================================================
# 4. HELPER FUNCTIONS
# ==================================================


def is_admin(chat_id: int) -> bool:
    """Return True if the given chat_id matches ADMIN_ID."""
    return ADMIN_ID is not None and chat_id == ADMIN_ID


def load_users() -> Set[int]:
    """Load registered user chat_ids from USERS_FILE."""
    if not os.path.exists(USERS_FILE):
        return set()
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(int(x) for x in data)
    except Exception as e:
        logger.warning(f"Failed to load users file: {e}")
        return set()


def save_user_to_file(chat_id: int) -> None:
    """Persist a new chat_id into USERS_FILE."""
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        try:
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(users), f)
        except Exception as e:
            logger.error(f"Failed to save users file: {e}")


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Return the main reply keyboard."""
    keyboard = [
        [
            KeyboardButton("🇰🇭 → 🇺🇸🇨🇳 (Learner)"),
            KeyboardButton("🇺🇸/🇨🇳 → 🇰🇭 (Foreigner)"),
        ],
        [
            KeyboardButton("🇰🇭 → 🇰🇷 (Korean)"),
            KeyboardButton("🇰🇭 → 🇯🇵 (Japanese)"),
        ],
        [
            KeyboardButton("🇰🇭 → 🇵🇭 (Filipino)"),
        ],
        [
            KeyboardButton("✏️ Grammar Tools"),
            KeyboardButton("🖼 Screenshot OCR"),
        ],
        [
            KeyboardButton("📩 Feedback"),
            KeyboardButton("ℹ️ Help / Guide"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def detect_mode_from_text(text: str) -> str:
    """
    Simple heuristic:
      - Khmer only         -> learner
      - Latin/Chinese only -> foreigner
      - Mixed              -> learner
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

    logger.info("Auto-detected mode from text='%s...': %s", text[:30], mode)
    return mode


async def chat_with_system_prompt(system_prompt: str, user_text: str) -> str:
    """Call Groq chat model with a system prompt + user content."""
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
            max_completion_tokens=1024,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error("chat_with_system_prompt error: %s", e, exc_info=True)
        return "⚠️ Error connecting to AI."


async def get_ai_response(chat_id: int, user_text: str) -> str:
    """Main translation / tutor logic based on user mode."""
    mode = USER_MODES.get(chat_id, "auto")

    if mode == "auto":
        mode = detect_mode_from_text(user_text)
        USER_MODES[chat_id] = mode

    if mode == "foreigner":
        system_prompt = PROMPT_FOREIGNER
    elif mode == "korean":
        system_prompt = PROMPT_KOREAN_LEARNER
    elif mode == "japanese":
        system_prompt = PROMPT_JAPANESE_LEARNER
    elif mode == "filipino":
        system_prompt = PROMPT_FILIPINO_LEARNER
    else:
        # default Khmer learner (EN + CN)
        system_prompt = PROMPT_KHMER_LEARNER

    logger.info("Using mode='%s' for chat_id=%s", mode, chat_id)
    return await chat_with_system_prompt(system_prompt, user_text)


async def send_long_message(update: Update, text: str) -> None:
    """Split long messages to respect Telegram 4096-char limit."""
    if not update.message or not text:
        return

    max_len = 4000
    if len(text) <= max_len:
        await update.message.reply_text(text)
        return

    for i in range(0, len(text), max_len):
        chunk = text[i : i + max_len]
        await update.message.reply_text(chunk)


# ==================================================
# 5. SCHEDULING ALERT
# ==================================================


async def send_scheduled_alert(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send automatic messages to all registered users."""
    message: str = context.job.data
    users = load_users()
    logger.info("⏰ Auto-Sending Alert to %d users: %r", len(users), message)

    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning("Failed to send scheduled alert to %s: %s", uid, e)


# ==================================================
# 6. COMMAND HANDLERS (CORE)
# ==================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command: welcome message + main keyboard."""
    if not update.message:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    save_user_to_file(chat_id)
    USER_MODES.setdefault(chat_id, "auto")

    msg = (
        f"👋 **សួស្តី {user.first_name}! សូមស្វាគមន៍មកកាន់ AI Language Tutor!**\n\n"
        "👨‍🏫 **ខ្ញុំអាចជួយអ្នករៀនភាសា អង់គ្លេស និង ចិន។**\n\n"
        "📚 **មុខងារសំខាន់ៗ:**\n"
        "• Khmer → English + Chinese\n"
        "• English/Chinese → Khmer\n"
        "• Khmer → Korean / Japanese / Filipino\n"
        "• 🖼 Screenshot OCR Translate\n"
        "• ✏️ Grammar Correction: `/kmgrammar`, `/enggrammar`, `/cngrammar`\n"
        "• 🔍 Explain sentence: `/explain ...`\n"
        "• 👤 Profile: `/profile`\n"
        "• ♻️ Reset: `/reset`\n\n"
        "📌 Mode ដំបូងកំណត់ស្វ័យប្រវត្តិតាមភាសាសារ។\n"
        "👇 **សូមចុចប៊ូតុងខាងក្រោម ដើម្បីចាប់ផ្តើម!**"
    )

    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help / usage guide."""
    if not update.message:
        return

    msg = (
        "📖 **AI Language Tutor Bot – Help Guide**\n\n"
        "🌐 Translation Commands\n"
        "• `/mode learner`   – Khmer → English + Chinese\n"
        "• `/mode foreigner` – English/Chinese → Khmer\n"
        "• `/mode korean`    – Khmer → Korean (mode)\n"
        "• `/mode japanese`  – Khmer → Japanese (mode)\n"
        "• `/mode filipino`  – Khmer → Filipino (mode)\n"
        "• `/ko` text        – Quick Khmer → Korean\n"
        "• `/ja` text        – Quick Khmer → Japanese\n"
        "• `/ph` text        – Quick Khmer → Filipino\n\n"
        "✏️ Grammar Correction\n"
        "• Khmer: `/kmgrammar ប្រយោគភាសាខ្មែរ...`\n"
        "• English: `/enggrammar your English sentence...`\n"
        "• Chinese: `/cngrammar 你的中文句子...`\n\n"
        "🔍 Sentence Explanation\n"
        "• `/explain sentence` – ពន្យល់អត្ថន័យ + vocab + examples ជាភាសាខ្មែរ\n\n"
        "👤 User Tools\n"
        "• `/profile` – ព័ត៌មានអំពី account របស់អ្នកក្នុង bot\n"
        "• `/reset` – កំណត់ Mode និង counter សារឡើងវិញ\n"
        "• `/menu` – បង្ហាញប៊ូតុងមេឡើងវិញ\n\n"
        "🖼 Screenshot OCR\n"
        "• ផ្ញើ screenshot/រូបមានអក្សរ → Bot អាន OCR + បកប្រែ\n\n"
        "📩 Feedback\n"
        "• `/feedback សារ​របស់​អ្នក`\n\n"
        "🛠 Admin only\n"
        "• `/broadcast text` – Send announcement to all users\n"
        "• `/stats` – View bot statistics\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show short about info."""
    if not update.message:
        return

    msg = (
        "ℹ️ **About AI Language Tutor Bot**\n\n"
        "• Khmer ⇄ English ⇄ Chinese tutor\n"
        "• Extra modes: Korean, Japanese, Filipino\n"
        "• Screenshot OCR via Groq Vision\n"
        "• Grammar correction (Khmer, English, Chinese)\n"
        "• Sentence explanation tool (`/explain`)\n"
        "• Auto-detect mode\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show main menu keyboard again."""
    if not update.message:
        return

    await update.message.reply_text(
        "📋 **Main Menu**\nសូមជ្រើសរើស Mode ឬ Tools ពីប៊ូតុងខាងក្រោម 👇",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(),
    )


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User feedback → forward to admin."""
    if not update.message:
        return

    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text(
            "សូមប្រើ៖ `/feedback សារ​របស់​អ្នក`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if ADMIN_ID is None:
        await update.message.reply_text("⚠️ ADMIN_ID មិនត្រូវបានកំណត់ទេ។")
        return

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 Feedback from {update.effective_user.id}: {msg}",
        )
        await update.message.reply_text("✅ Feedback sent.")
    except Exception as e:
        logger.error("Failed to send feedback to ADMIN: %s", e)
        await update.message.reply_text("⚠️ មិនអាចផ្ញើ Feedback ទៅ Admin បានទេ។")


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get or set user mode (auto / learner / foreigner / korean / japanese / filipino)."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    current = USER_MODES.get(chat_id, "auto")

    if not context.args:
        txt = (
            "🔧 **Current Mode:** `{}`\n\n"
            "• `/mode learner`    – Khmer Learner (KM → EN + CN)\n"
            "• `/mode foreigner`  – Foreigner (EN/CN → KM)\n"
            "• `/mode korean`     – Korean Learner (KM → KO)\n"
            "• `/mode japanese`   – Japanese Learner (KM → JA)\n"
            "• `/mode filipino`   – Filipino Learner (KM → PH)\n"
            "• `/mode auto`       – Auto-detect\n"
        ).format(current)
        await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)
        return

    arg = context.args[0].lower()

    if arg in ["learner", "khmer", "student"]:
        USER_MODES[chat_id] = "learner"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Khmer Learner (KM → EN + CN)**",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif arg in ["foreigner", "en", "eng", "english"]:
        USER_MODES[chat_id] = "foreigner"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Foreigner (EN/CN → KM)**",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif arg in ["korean", "kr"]:
        USER_MODES[chat_id] = "korean"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Korean Learner (KM → KO)**",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif arg in ["japanese", "jp"]:
        USER_MODES[chat_id] = "japanese"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Japanese Learner (KM → JA)**",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif arg in ["filipino", "tagalog", "ph"]:
        USER_MODES[chat_id] = "filipino"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Filipino Learner (KM → PH)**",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif arg in ["auto", "detect"]:
        USER_MODES[chat_id] = "auto"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Auto-detect**",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "⚠️ Mode មិនស្គាល់។ ប្រើ: learner / foreigner / korean / japanese / filipino / auto",
            parse_mode=ParseMode.MARKDOWN,
        )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show information about current user inside the bot."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    users = load_users()
    registered = chat_id in users
    mode = USER_MODES.get(chat_id, "auto")
    msg_count = USER_STATS.get(chat_id, 0)

    msg = (
        "👤 **User Profile (in this bot)**\n\n"
        f"• ID: `{chat_id}`\n"
        f"• Registered: `{'Yes' if registered else 'No'}`\n"
        f"• Current mode: `{mode}`\n"
        f"• Messages this run: `{msg_count}`\n\n"
        "📌 អ្នកអាចប្តូរ Mode ដោយប្រើ `/mode ...`\n"
        "📌 ប្រើ `/reset` ប្រសិនបើចង់ចាប់ផ្តើមថ្មី។"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset user-specific data (mode + message count)."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    USER_MODES[chat_id] = "auto"
    USER_STATS[chat_id] = 0

    await update.message.reply_text(
        "♻️ **Reset complete!**\n"
        "• Mode ត្រូវបានកំណត់វិញទៅ `auto`\n"
        "• Message counter ត្រូវបានកំណត់ជា `0`\n\n"
        "អាចចាប់ផ្តើមជាមួយប្រយោគថ្មីបានហើយ 😄",
        parse_mode=ParseMode.MARKDOWN,
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only broadcast to all registered users."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return

    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text(
            "ប្រើ៖ `/broadcast សារ​ត្រូវ​ផ្ញើ`",
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
            logger.warning("Failed to send broadcast to %s: %s", uid, e)

    await update.message.reply_text(
        f"✅ Broadcast sent to {sent} users. Failed: {failed}."
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only bot statistics."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return

    users = load_users()
    total_users = len(users)
    total_msgs = sum(USER_STATS.values()) if USER_STATS else 0

    mode_counts = {
        "auto": 0,
        "learner": 0,
        "foreigner": 0,
        "korean": 0,
        "japanese": 0,
        "filipino": 0,
    }
    for m in USER_MODES.values():
        if m in mode_counts:
            mode_counts[m] += 1

    msg = (
        "📊 **Bot Stats**\n\n"
        f"• Registered users: `{total_users}`\n"
        f"• Active users in memory: `{len(USER_MODES)}`\n"
        f"• Total messages this run: `{total_msgs}`\n\n"
        "Modes:\n"
        f"• auto: `{mode_counts['auto']}`\n"
        f"• learner: `{mode_counts['learner']}`\n"
        f"• foreigner: `{mode_counts['foreigner']}`\n"
        f"• korean: `{mode_counts['korean']}`\n"
        f"• japanese: `{mode_counts['japanese']}`\n"
        f"• filipino: `{mode_counts['filipino']}`\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ==================================================
# 7. GRAMMAR, EXPLAIN & LANGUAGE SHORT COMMANDS
# ==================================================


async def kmgrammar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Khmer grammar correction."""
    if not update.message:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "ប្រើ៖ `/kmgrammar ប្រយោគភាសាខ្មែរ​របស់​អ្នក`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("✏️ កំពុងពិនិត្យវេយ្យាករណ៍ភាសាខ្មែរ...")
    reply = await chat_with_system_prompt(PROMPT_KM_GRAMMAR, text)
    await send_long_message(update, reply)


async def enggrammar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """English grammar correction."""
    if not update.message:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "Use: `/enggrammar your English sentence`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("✏️ Checking English grammar...")
    reply = await chat_with_system_prompt(PROMPT_EN_GRAMMAR, text)
    await send_long_message(update, reply)


async def cngrammar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chinese grammar correction."""
    if not update.message:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "使用: `/cngrammar 你的中文句子`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("✏️ 正在检查中文语法 / កំពុងពិនិត្យភាសាចិន...")
    reply = await chat_with_system_prompt(PROMPT_CN_GRAMMAR, text)
    await send_long_message(update, reply)


async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain a sentence (Khmer/English/Chinese) in simple Khmer."""
    if not update.message:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "ប្រើ៖ `/explain ប្រយោគ​របស់​អ្នក` (Kh/EN/CN)\n"
            "ឧ. `/explain I will go to school tomorrow.`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🔍 កំពុងពន្យល់ប្រយោគរបស់អ្នក...")
    reply = await chat_with_system_prompt(PROMPT_EXPLAIN, text)
    await send_long_message(update, reply)


async def ko_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick Khmer → Korean translation."""
    if not update.message:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "ប្រើ៖ `/ko ប្រយោគភាសាខ្មែររបស់អ្នក`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🇰🇷 កំពុងបកប្រែទៅភាសាកូរ៉េ...")
    reply = await chat_with_system_prompt(PROMPT_KOREAN_LEARNER, text)
    await send_long_message(update, reply)


async def ja_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick Khmer → Japanese translation."""
    if not update.message:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "ប្រើ៖ `/ja ប្រយោគភាសាខ្មែររបស់អ្នក`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🇯🇵 កំពុងបកប្រែទៅភាសាជប៉ុន...")
    reply = await chat_with_system_prompt(PROMPT_JAPANESE_LEARNER, text)
    await send_long_message(update, reply)


async def ph_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick Khmer → Filipino translation."""
    if not update.message:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "ប្រើ៖ `/ph ប្រយោគភាសាខ្មែររបស់អ្នក`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🇵🇭 កំពុងបកប្រែទៅភាសាហ្វីលីពីន...")
    reply = await chat_with_system_prompt(PROMPT_FILIPINO_LEARNER, text)
    await send_long_message(update, reply)


# ==================================================
# 8. PHOTO HANDLER (VISION OCR)
# ==================================================


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Use Groq Vision model to OCR the image, then translate like normal text.
    """
    if not client:
        if update.message:
            await update.message.reply_text("⚠️ Server Error: Missing API Key.")
        return

    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id
    USER_STATS[chat_id] = USER_STATS.get(chat_id, 0) + 1

    # Get largest version of photo
    photo = update.message.photo[-1]
    try:
        file = await photo.get_file()
        ba = await file.download_as_bytearray()
        image_bytes = bytes(ba)
    except Exception as e:
        logger.error("Failed to download image: %s", e, exc_info=True)
        await update.message.reply_text(
            "⚠️ មិនអាចទាញយករូបភាពបានទេ។ សូមសាកល្បងម្ដងទៀត។"
        )
        return

    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    await update.message.reply_text("🖼 កំពុងអានអក្សរពីរូបភាព...")

    # Groq Vision: text + image_url content format (OpenAI compatible)
    try:
        vision_resp = client.chat.completions.create(
            model=GROQ_MODEL_VISION,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract ALL readable text from this image. "
                                "Return plain text only, no explanation."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        },
                    ],
                }
            ],
            temperature=0,
            max_completion_tokens=1024,
        )

        ocr_text = vision_resp.choices[0].message.content or ""
        ocr_text = str(ocr_text).strip()
    except Exception as e:
        logger.error("Groq Vision OCR error: %s", e, exc_info=True)
        await update.message.reply_text(
            "⚠️ OCR Error: មិនអាចអានអក្សរពីរូបភាពបានទេ។"
        )
        return

    if not ocr_text:
        await update.message.reply_text(
            "⚠️ មិនរកឃើញអក្សរ​ក្នុងរូបភាពទេ។ សូមប្រើរូបដែលអក្សរច្បាស់ជាងនេះ។"
        )
        return

    # Ensure user is registered + mode available
    save_user_to_file(chat_id)
    USER_MODES.setdefault(chat_id, "auto")

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    reply = await get_ai_response(chat_id, ocr_text)
    if not reply:
        reply = "⚠️ No response from AI."

    header = "📷 **បកប្រែពីរូបភាព (Screenshot Translation):**\n\n"
    await send_long_message(update, header + str(reply))


# ==================================================
# 9. TEXT HANDLER
# ==================================================


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main text message handler (mode buttons + normal chat)."""
    if not update.message or not update.message.text:
        return

    text = update.message.text
    chat_id = update.effective_chat.id

    USER_STATS[chat_id] = USER_STATS.get(chat_id, 0) + 1
    logger.info(
        "Message from %s: %s... (count=%s)",
        chat_id,
        text[:50],
        USER_STATS[chat_id],
    )

    USER_MODES.setdefault(chat_id, "auto")

    # --- Keyboard buttons ---
    if text == "🇰🇭 → 🇺🇸🇨🇳 (Learner)":
        USER_MODES[chat_id] = "learner"
        await update.message.reply_text(
            "✅ Mode: Khmer Learner\n"
            "សរសេរ ខ្មែរ/EN → ខ្ញុំនឹងបកប្រែ EN + CN (មាន Pinyin).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "🇺🇸/🇨🇳 → 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = "foreigner"
        await update.message.reply_text(
            "✅ Mode: Foreigner\n"
            "វាយ English ឬ Chinese → ខ្ញុំបកប្រែជាខ្មែរ។",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "🇰🇭 → 🇰🇷 (Korean)":
        USER_MODES[chat_id] = "korean"
        await update.message.reply_text(
            "✅ Mode: Korean Learner\n"
            "វាយប្រយោគខ្មែរ → ខ្ញុំនឹងបកប្រែជាកូរ៉េ (Hangul + Romanization + Khmer meaning).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "🇰🇭 → 🇯🇵 (Japanese)":
        USER_MODES[chat_id] = "japanese"
        await update.message.reply_text(
            "✅ Mode: Japanese Learner\n"
            "វាយប្រយោគខ្មែរ → ខ្ញុំនឹងបកប្រែជាជប៉ុន (Japanese + Romaji + Khmer meaning).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "🇰🇭 → 🇵🇭 (Filipino)":
        USER_MODES[chat_id] = "filipino"
        await update.message.reply_text(
            "✅ Mode: Filipino Learner\n"
            "វាយប្រយោគខ្មែរ → ខ្ញុំនឹងបកប្រែជាភាសាហ្វីលីពីន (Filipino + Khmer meaning).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "✏️ Grammar Tools":
        await update.message.reply_text(
            "✏️ **Grammar Tools**\n\n"
            "• Khmer: `/kmgrammar ប្រយោគភាសាខ្មែរ...`\n"
            "• English: `/enggrammar your English sentence...`\n"
            "• Chinese: `/cngrammar 你的中文句子...`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "🖼 Screenshot OCR":
        await update.message.reply_text(
            "🖼 **Screenshot OCR Guide**\n\n"
            "1️⃣ ថត screenshot ឬរូបមានអក្សរ\n"
            "2️⃣ ផ្ញើរូបនោះមក bot (photo)\n"
            "3️⃣ Bot នឹងអានអក្សរ និងបកប្រែស្វ័យប្រវត្តិ",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "📩 Feedback":
        await update.message.reply_text(
            "ប្រើ៖ `/feedback សារ​របស់​អ្នក`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "ℹ️ Help / Guide":
        await help_command(update, context)
        return

    # --- Normal text → AI tutor ---
    save_user_to_file(chat_id)
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    reply = await get_ai_response(chat_id, text)
    if not reply:
        reply = "⚠️ No response from AI."
    else:
        reply = str(reply)

    await send_long_message(update, reply)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all for unknown commands."""
    if not update.message:
        return

    cmd = update.message.text
    msg = (
        f"⚠️ Command `{cmd}` មិនស្គាល់ទេ។\n"
        "ប្រើ `/help` ដើម្បីមើល commands ទាំងអស់។"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ==================================================
# 10. MAIN ENTRYPOINT
# ==================================================


def main() -> None:
    """Entrypoint: build application, register handlers, start polling."""
    if keep_alive:
        keep_alive()

    if not TELEGRAM_TOKEN:
        logger.error("❌ Error: TELEGRAM_TOKEN missing.")
        return

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
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("reset", reset_command))

    # Grammar, explain & quick language commands
    app.add_handler(CommandHandler("kmgrammar", kmgrammar_command))
    app.add_handler(CommandHandler("enggrammar", enggrammar_command))
    app.add_handler(CommandHandler("cngrammar", cngrammar_command))
    app.add_handler(CommandHandler("explain", explain_command))
    app.add_handler(CommandHandler("ko", ko_command))
    app.add_handler(CommandHandler("ja", ja_command))
    app.add_handler(CommandHandler("ph", ph_command))

    # Photos (screenshots)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Text messages (non-command)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Scheduler (daily greetings)
    jq = app.job_queue
    jq.run_daily(
        send_scheduled_alert,
        time=dt_time(1, 0),
        data="☀️ អរុណសួស្តី! Good Morning!",
        name="morning",
    )
    jq.run_daily(
        send_scheduled_alert,
        time=dt_time(6, 0),
        data="☕ ទិវាសួស្តី! Good Afternoon!",
        name="afternoon",
    )
    jq.run_daily(
        send_scheduled_alert,
        time=dt_time(13, 0),
        data="🌙 រាត្រីសួស្តី! Good Evening!",
        name="evening",
    )

    logger.info("✅ Bot is running with Scheduler...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
