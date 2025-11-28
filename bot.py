#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Language Tutor Telegram Bot
Khmer ⇄ English ⇄ Chinese + OCR + Grammar Tools + Extra Features

Author: Kobsari (refactored + improved by ChatGPT)
"""

import asyncio
import base64
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import time as dt_time
from logging.handlers import RotatingFileHandler
from typing import Dict, Set, Optional
from zoneinfo import ZoneInfo  # For Cambodia timezone

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
    ADMIN_ID: Optional[int] = int(ADMIN_ID_RAW.strip()) if ADMIN_ID_RAW else None
except Exception:
    ADMIN_ID = None

GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
GROQ_MODEL_VISION = "meta-llama/llama-4-scout-17b-16e-instruct"

USERS_FILE = "users.json"

# Keyboard button labels (centralized to avoid typos)
BTN_LEARNER = "🇰🇭 → 🇺🇸🇨🇳 (Learner)"
BTN_FOREIGNER = "🇺🇸/🇨🇳 → 🇰🇭 (Foreigner)"
BTN_GRAMMAR = "✏️ Grammar Tools"
BTN_OCR = "🖼 Screenshot OCR"
BTN_FEEDBACK = "📩 Feedback"
BTN_HELP = "ℹ️ Help / Guide"

# USER_MODES: {chat_id: 'auto' | 'learner' | 'foreigner'}
USER_MODES: Dict[int, str] = {}
# USER_STATS: {chat_id: message_count (in-memory only for this run)}
USER_STATS: Dict[int, int] = {}

# Timezone for scheduler (Cambodia)
TIMEZONE = ZoneInfo("Asia/Phnom_Penh")


@dataclass
class BotConfig:
    """Runtime configuration + helpers."""
    telegram_token: Optional[str] = TELEGRAM_TOKEN
    groq_api_key: Optional[str] = GROQ_API_KEY
    admin_id: Optional[int] = ADMIN_ID
    users_file: str = USERS_FILE
    groq_client: Optional[Groq] = field(default=None, init=False)

    def init_groq_client(self) -> None:
        """Initialize Groq client if possible."""
        if self.groq_api_key:
            try:
                self.groq_client = Groq(api_key=self.groq_api_key)
            except Exception as e:  # pragma: no cover - defensive
                logging.getLogger(__name__).error(
                    "Failed to initialize Groq client: %s", e, exc_info=True
                )
                self.groq_client = None
        else:
            self.groq_client = None
            logging.getLogger(__name__).warning(
                "⚠️ GROQ_API_KEY is missing! AI responses will not work."
            )

    @property
    def has_groq(self) -> bool:
        return self.groq_client is not None


CONFIG = BotConfig()
CONFIG.init_groq_client()

# ==================================================
# 2. LOGGING
# ==================================================

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Avoid duplicate handlers if module is imported multiple times
if not root_logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# ==================================================
# 3. SYSTEM PROMPTS
# ==================================================

PROMPT_KHMER_LEARNER = """
You are an expert Multi-Language Tutor (English & Chinese) for Khmer speakers.

YOUR TASK:
1. Analyze the user's input.
2. Provide the ENGLISH translation/correction with Khmer Phonetics.
3. Provide the CHINESE translation with PINYIN and Khmer Phonetics.
4. Provide the KHMER meaning.
5. ALWAYS provide a Usage Example in ALL 3 languages, INCLUDING PINYIN for Chinese.

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
    return CONFIG.admin_id is not None and chat_id == CONFIG.admin_id


def load_users() -> Set[int]:
    """Load registered user chat_ids from USERS_FILE."""
    if not os.path.exists(CONFIG.users_file):
        return set()
    try:
        with open(CONFIG.users_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(int(x) for x in data)
    except Exception as e:
        logger.warning("Failed to load users file: %s", e)
        return set()


def save_user_to_file(chat_id: int) -> None:
    """Persist a new chat_id into USERS_FILE."""
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        try:
            with open(CONFIG.users_file, "w", encoding="utf-8") as f:
                json.dump(sorted(list(users)), f)
        except Exception as e:
            logger.error("Failed to save users file: %s", e)


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Return the main reply keyboard."""
    keyboard = [
        [KeyboardButton(BTN_LEARNER), KeyboardButton(BTN_FOREIGNER)],
        [KeyboardButton(BTN_GRAMMAR), KeyboardButton(BTN_OCR)],
        [KeyboardButton(BTN_FEEDBACK), KeyboardButton(BTN_HELP)],
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


async def _groq_chat_completion(**kwargs) -> str:
    """
    Run Groq chat.completions.create in a background thread
    so we don't block the asyncio event loop.
    """
    if not CONFIG.has_groq:
        return "⚠️ Server Error: Missing or invalid GROQ_API_KEY."

    def _call():
        resp = CONFIG.groq_client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    try:
        return await asyncio.to_thread(_call)
    except Exception as e:  # pragma: no cover - network errors
        logger.error("Groq chat completion error: %s", e, exc_info=True)
        return "⚠️ Error connecting to AI."


async def chat_with_system_prompt(system_prompt: str, user_text: str) -> str:
    """Call Groq chat model with a system prompt + user content."""
    return await _groq_chat_completion(
        model=GROQ_MODEL_CHAT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=0.3,
        max_completion_tokens=1024,
    )


async def get_ai_response(chat_id: int, user_text: str) -> str:
    """Main translation / tutor logic based on user mode."""
    mode = USER_MODES.get(chat_id, "auto")

    if mode == "auto":
        mode = detect_mode_from_text(user_text)
        USER_MODES[chat_id] = mode

    system_prompt = PROMPT_FOREIGNER if mode == "foreigner" else PROMPT_KHMER_LEARNER
    logger.info("Using mode='%s' for chat_id=%s", mode, chat_id)
    return await chat_with_system_prompt(system_prompt, user_text)


async def send_long_message(update: Update, text: str) -> None:
    """Split long messages to respect Telegram 4096-char limit."""
    if not update.message or not text:
        return

    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i: i + max_len]
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


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
        except Exception as e:  # pragma: no cover - network issues
            logger.warning("Failed to send scheduled alert to %s: %s", uid, e)


def schedule_daily_jobs(jq) -> None:
    """Register all daily greeting jobs using local Cambodia time."""
    # 🌅 Morning greeting – 07:00
    jq.run_daily(
        send_scheduled_alert,
        time=dt_time(7, 0, tzinfo=TIMEZONE),
        data="☀️ អរុណសួស្តី! Good morning! ប្រ្ដើមថ្ងៃថ្មីឲ្យមានការសប្បាយរីករាយបំផុតណា 😄",
        name="morning_greeting",
    )

    # 🌞 Midday greeting – 12:30
    jq.run_daily(
        send_scheduled_alert,
        time=dt_time(12, 30, tzinfo=TIMEZONE),
        data="☕ ទិវាសួស្តី! Good afternoon! កុំភ្លេចសម្រាកបន្តិច ហូបអាហារឲ្យពេញ 😋",
        name="noon_greeting",
    )

    # 🌙 Evening greeting – 20:30
    jq.run_daily(
        send_scheduled_alert,
        time=dt_time(20, 30, tzinfo=TIMEZONE),
        data="🌙 រាត្រីសួស្តី! Good evening! សូមឲ្យឈប់សម្រាកល្អ និងសុបិន់ល្អ 😴",
        name="evening_greeting",
    )


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
    USER_STATS.setdefault(chat_id, 0)

    msg = (
        f"👋 **សួស្តី {user.first_name}! សូមស្វាគមន៍មកកាន់ AI Language Tutor!**\n\n"
        "👨‍🏫 **ខ្ញុំអាចជួយអ្នករៀនភាសា អង់គ្លេស និង ចិន។**\n\n"
        "📚 **មុខងារសំខាន់ៗ:**\n"
        "• 🇰🇭 → 🇺🇸🇨🇳  Khmer Learner Mode\n"
        "• 🇺🇸/🇨🇳 → 🇰🇭 Foreigner Mode\n"
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
        "📖 **ជំនួយប្រើ AI Language Tutor Bot**\n\n"
        "🌐 Translation Modes\n"
        f"• `{BTN_LEARNER}` – Khmer → English+Chinese\n"
        f"• `{BTN_FOREIGNER}` – English/Chinese → Khmer\n"
        "• `/mode learner`, `/mode foreigner`, `/mode auto`\n\n"
        "✏️ Grammar Correction\n"
        "• Khmer: `/kmgrammar ប្រយោគភាសាខ្មែរ...`\n"
        "• English: `/enggrammar your English sentence...`\n"
        "• Chinese: `/cngrammar 你的中文句子...`\n\n"
        "🔍 Sentence Explanation\n"
        "• `/explain sentence` – ពន្យល់អត្ថន័យ + vocab + examples ជាភាសាខ្មែរ\n\n"
        "👤 User Tools\n"
        "• `/profile` – ព័ត៌មានអំពី account របស់អ្នកក្នុង bot\n"
        "• `/reset` – កំណត់ Mode និង counter សារឡើងវិញ\n\n"
        "🖼 Screenshot OCR\n"
        "• ផ្ញើ screenshot/រូបមានអក្សរ → Bot អាន OCR + បកប្រែ\n\n"
        "📩 Feedback\n"
        "• `/feedback សារ​របស់​អ្នក`\n\n"
        "Admin only: `/stats`, `/broadcast text`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show short about info."""
    if not update.message:
        return

    msg = (
        "ℹ️ **About AI Language Tutor Bot**\n\n"
        "• Khmer ⇄ English ⇄ Chinese tutor\n"
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

    msg_text = " ".join(context.args)
    if not msg_text:
        await update.message.reply_text(
            "សូមប្រើ៖ `/feedback សារ​របស់​អ្នក`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if CONFIG.admin_id is None:
        await update.message.reply_text("⚠️ ADMIN_ID មិនត្រូវបានកំណត់ទេ។")
        return

    try:
        await context.bot.send_message(
            chat_id=CONFIG.admin_id,
            text=f"📩 Feedback from {update.effective_user.id}: {msg_text}",
        )
        await update.message.reply_text("✅ Feedback sent.")
    except Exception as e:  # pragma: no cover
        logger.error("Failed to send feedback to ADMIN: %s", e)
        await update.message.reply_text("⚠️ មិនអាចផ្ញើ Feedback ទៅ Admin បានទេ។")


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get or set user mode (auto / learner / foreigner)."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    current = USER_MODES.get(chat_id, "auto")

    if not context.args:
        txt = (
            "🔧 **Current Mode:** `{}`\n\n"
            "• `/mode learner`   – Khmer Learner\n"
            "• `/mode foreigner` – Foreigner\n"
            "• `/mode auto`      – Auto-detect\n"
        ).format(current)
        await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)
        return

    arg = context.args[0].lower()

    if arg in ["learner", "khmer", "student"]:
        USER_MODES[chat_id] = "learner"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Khmer Learner**",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif arg in ["foreigner", "en", "eng", "english"]:
        USER_MODES[chat_id] = "foreigner"
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Foreigner (EN/CN -> KM)**",
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
            "⚠️ Mode មិនស្គាល់។ ប្រើ: learner / foreigner / auto",
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
        await update.message.reply_text("⚠️ You are not allowed to use this command.")
        return

    msg_text = " ".join(context.args)
    if not msg_text:
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
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg_text}")
            sent += 1
            await asyncio.sleep(0.1)
        except Exception as e:  # pragma: no cover
            failed += 1
            logger.warning("Failed to send broadcast to %s: %s", uid, e)

    await update.message.reply_text(
        f"✅ Broadcast sent to {sent} users. Failed: {failed}.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only bot statistics."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⚠️ You are not allowed to use this command.")
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
        f"• Registered users: `{total_users}`\n"
        f"• Active users in memory: `{len(USER_MODES)}`\n"
        f"• Total messages this run: `{total_msgs}`\n\n"
        "Modes:\n"
        f"• auto: `{mode_counts['auto']}`\n"
        f"• learner: `{mode_counts['learner']}`\n"
        f"• foreigner: `{mode_counts['foreigner']}`\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ==================================================
# 7. GRAMMAR & EXPLAIN COMMANDS
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


# ==================================================
# 8. PHOTO HANDLER (VISION OCR)
# ==================================================


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Use Groq Vision model to OCR the image, then translate like normal text.
    """
    if not CONFIG.has_groq:
        if update.message:
            await update.message.reply_text("⚠️ Server Error: Missing or invalid GROQ_API_KEY.")
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
    except Exception as e:  # pragma: no cover
        logger.error("Failed to download image: %s", e, exc_info=True)
        await update.message.reply_text(
            "⚠️ មិនអាចទាញយករូបភាពបានទេ។ សូមសាកល្បងម្ដងទៀត។"
        )
        return

    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    await update.message.reply_text("🖼 កំពុងអានអក្សរពីរូបភាព...")

    try:
        ocr_text = await _groq_chat_completion(
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
        ocr_text = (ocr_text or "").strip()
    except Exception as e:  # pragma: no cover
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

    text = update.message.text.strip()
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
    if text == BTN_LEARNER:
        USER_MODES[chat_id] = "learner"
        await update.message.reply_text(
            "✅ Mode: Khmer Learner\n"
            "សរសេរ ខ្មែរ/EN → ខ្ញុំនឹងបកប្រែ EN + CN (មាន Pinyin).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == BTN_FOREIGNER:
        USER_MODES[chat_id] = "foreigner"
        await update.message.reply_text(
            "✅ Mode: Foreigner\n"
            "វាយ English ឬ Chinese → ខ្ញុំបកប្រែជាខ្មែរ។",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == BTN_GRAMMAR:
        await update.message.reply_text(
            "✏️ **Grammar Tools**\n\n"
            "• Khmer: `/kmgrammar ប្រយោគភាសាខ្មែរ...`\n"
            "• English: `/enggrammar your English sentence...`\n"
            "• Chinese: `/cngrammar 你的中文句子...`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == BTN_OCR:
        await update.message.reply_text(
            "🖼 **Screenshot OCR Guide**\n\n"
            "1️⃣ ថត screenshot ឬរូបមានអក្សរ\n"
            "2️⃣ ផ្ញើរូបនោះមក bot (photo)\n"
            "3️⃣ Bot នឹងអានអក្សរ និងបកប្រែស្វ័យប្រវត្តិ",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == BTN_FEEDBACK:
        await update.message.reply_text(
            "ប្រើ៖ `/feedback សារ​របស់​អ្នក`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == BTN_HELP:
        await help_command(update, context)
        return

    # --- Normal text → AI tutor ---
    save_user_to_file(chat_id)

    if not CONFIG.has_groq:
        await update.message.reply_text(
            "⚠️ Server Error: Missing or invalid GROQ_API_KEY.\n"
            "សូមពិនិត្យ ENV variable `GROQ_API_KEY` នៅលើ server របស់អ្នក។",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

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

    if not CONFIG.telegram_token:
        logger.error("❌ Error: TELEGRAM_BOT_TOKEN missing.")
        return

    app = ApplicationBuilder().token(CONFIG.telegram_token).build()

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

    # Grammar & explain commands
    app.add_handler(CommandHandler("kmgrammar", kmgrammar_command))
    app.add_handler(CommandHandler("enggrammar", enggrammar_command))
    app.add_handler(CommandHandler("cngrammar", cngrammar_command))
    app.add_handler(CommandHandler("explain", explain_command))

    # Photos (screenshots)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Text messages (non-command)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Scheduler (daily greetings, Cambodia local time)
    jq = app.job_queue
    schedule_daily_jobs(jq)

    logger.info("✅ Bot is running with Scheduler...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
