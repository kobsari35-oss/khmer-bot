import os
import logging
import json
import asyncio
from datetime import time
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq

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

# USER_MODES: {chat_id: 'learner' | 'foreigner'}
USER_MODES = {}

if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    client = None
    print("⚠️ Warning: GROQ_API_KEY is missing!")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

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


def load_users():
    if not os.path.exists(USERS_FILE):
        return set()
    with open(USERS_FILE, 'r') as f:
        try:
            return set(json.load(f))
        except Exception as e:
            logger.warning(f"Failed to load users file: {e}")
            return set()


def save_user_to_file(chat_id):
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        try:
            with open(USERS_FILE, 'w') as f:
                json.dump(list(users), f)
        except Exception as e:
            logger.error(f"Failed to save users file: {e}")


def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳"), KeyboardButton("🇺🇸 -> 🇰🇭 (Foreigner)")],
        [KeyboardButton("📩 Feedback"), KeyboardButton("❓ Help/ជំនួយ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def get_ai_response(chat_id, user_text):
    if not client:
        return "⚠️ Server Error: Missing API Key."
    mode = USER_MODES.get(chat_id, 'learner')
    system_prompt = PROMPT_FOREIGNER if mode == 'foreigner' else PROMPT_KHMER_LEARNER

    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            model=GROQ_MODEL_CHAT,
            temperature=0.3,
            max_tokens=1500,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI Chat Error: {e}")
        return "⚠️ Error connecting to AI."


async def send_long_message(update: Update, text: str):
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
        chunk = text[i:i + max_len]
        await update.message.reply_text(chunk)

# ================= 4. SCHEDULING ALERT =================


async def send_scheduled_alert(context: ContextTypes.DEFAULT_TYPE):
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user_to_file(chat_id)

    if chat_id not in USER_MODES:
        USER_MODES[chat_id] = 'learner'

    msg = (
        f"👋 **សួស្តី {user.first_name}! សូមស្វាគមន៍មកកាន់ AI Language Tutor!**\n\n"
        "👨‍🏫 **ខ្ញុំអាចជួយអ្នករៀនភាសា អង់គ្លេស និង ចិន។**\n\n"
        "📚 **របៀបប្រើប្រាស់:**\n"
        "1️⃣ **🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳 (សិស្សរៀនភាសា)**\n"
        "• វាយជាខ្មែរ ឬអង់គ្លេស ខ្ញុំនឹងបកប្រែជា **អង់គ្លេស និង ចិន (មាន Pinyin)** ព្រមទាំងប្រាប់របៀបអាន។\n\n"
        "2️⃣ **🇺🇸 -> 🇰🇭 (Foreigner)**\n"
        "• For foreigners learning Khmer.\n\n"
        "👇 **សូមចុចប៊ូតុងខាងក្រោមដើម្បីចាប់ផ្តើម!**"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🆘 **ជំនួយ ប្រើ Bot**\n\n"
        "1️⃣ ជា​សិស្ស​ខ្មែរ រៀន អង់គ្លេស/ចិន:\n"
        "   • ចុចប៊ូតុង: 🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳\n"
        "   • សរសេរខ្មែរ ឬ អង់គ្លេស មក ខ្ញុំនឹងបកប្រែ EN + CN (មាន Pinyin) និងអត្ថន័យខ្មែរ។\n\n"
        "2️⃣ ជា Foreigner រៀន​ខ្មែរ:\n"
        "   • ចុចប៊ូតុង: 🇺🇸 -> 🇰🇭 (Foreigner)\n"
        "   • សរសេរ English / Chinese មក ខ្ញុំនឹងបកប្រែជា Khmer Script + Romanization + Cultural tip។\n\n"
        "3️⃣ ផ្ញើមតិយោបល់:\n"
        "   • ប្រើ: `/feedback សារ​របស់​អ្នក`\n\n"
        "4️⃣ ប្ដូរ Mode ដោយ command:\n"
        "   • `/mode learner`  សម្រាប់ Khmer Learner\n"
        "   • `/mode foreigner` សម្រាប់ Foreigner\n\n"
        "👇 អ្នកអាចចុច /menu ដើម្បីបង្ហាញប៊ូតុងម្ដងទៀត។"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 ម៉ឺនុយត្រូវបានបង្ហាញឡើងវិញ។ សូមជ្រើសរើស Mode ឬ Function ខាងក្រោម 🎛️",
        reply_markup=get_main_keyboard()
    )


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    if not msg:
        await update.message.reply_text("សូមប្រើ៖ `/feedback សារ​របស់​អ្នក`", parse_mode=ParseMode.MARKDOWN)
        return

    if ADMIN_ID:
        try:
            await context.bot.send_message(chat_id=int(ADMIN_ID), text=f"📩 Feedback: {msg}")
            await update.message.reply_text("✅ Feedback sent.")
        except Exception as e:
            logger.error(f"Failed to send feedback to ADMIN: {e}")
            await update.message.reply_text("⚠️ មិនអាចផ្ញើ Feedback ទៅ Admin បានទេ។")
    else:
        await update.message.reply_text("⚠️ ADMIN_ID មិនត្រូវបានកំណត់ទេ។")


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # មិនបានបញ្ចូល args => បង្ហាញ mode បច្ចុប្បន្ន និងរបៀបប្រើ
    if not context.args:
        current = USER_MODES.get(chat_id, 'learner')
        txt = (
            "🔧 **Current Mode:** `{}`\n\n"
            "ប្រើ:\n"
            "• `/mode learner`   សម្រាប់ 🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳 (Khmer Learner)\n"
            "• `/mode foreigner` សម្រាប់ 🇺🇸 -> 🇰🇭 (Foreigner)"
        ).format(current)
        await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)
        return

    arg = context.args[0].lower()
    if arg in ["learner", "khmer", "student"]:
        USER_MODES[chat_id] = 'learner'
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Khmer Learner**\nសរសេរខ្មែរ/អង់គ្លេស មកបាន!",
            parse_mode=ParseMode.MARKDOWN
        )
    elif arg in ["foreigner", "en", "eng", "english"]:
        USER_MODES[chat_id] = 'foreigner'
        await update.message.reply_text(
            "✅ Mode ផ្លាស់ប្ដូរ​ទៅ **Foreigner (English/Chinese -> Khmer)**",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "⚠️ Mode មិនស្គាល់។\nប្រើ: `/mode learner` ឬ `/mode foreigner`",
            parse_mode=ParseMode.MARKDOWN
        )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # មានសិទ្ធិ broadcast តែ ADMIN ប៉ុណ្ណោះ
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID):
        return

    msg = ' '.join(context.args)
    if not msg:
        await update.message.reply_text("សូមវាយសារ៖ `/broadcast សារ​ត្រូវ​ផ្ញើ`", parse_mode=ParseMode.MARKDOWN)
        return

    users = load_users()
    sent = 0
    failed = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
            sent += 1
            # បន្ថែមសម្រាកតូចៗ ដើម្បីជៀស Telegram flood limit
            await asyncio.sleep(0.1)
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to send broadcast to {uid}: {e}")

    await update.message.reply_text(f"✅ Broadcast sent to {sent} users. Failed: {failed}.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    chat_id = update.effective_chat.id

    # Handle buttons text
    if text == "🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳":
        USER_MODES[chat_id] = 'learner'
        await update.message.reply_text(
            "✅ **Mode: Khmer Learner**\nសរសេរមកបាន! ខ្ញុំនឹងចេញទាំង អង់គ្លេស និង ចិន។",
            parse_mode=ParseMode.MARKDOWN
        )
    elif text == "🇺🇸 -> 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = 'foreigner'
        await update.message.reply_text(
            "✅ **Mode: Foreigner Standard**",
            parse_mode=ParseMode.MARKDOWN
        )
    elif text == "📩 Feedback":
        await update.message.reply_text("Type: `/feedback [msg]`", parse_mode=ParseMode.MARKDOWN)
    elif text == "❓ Help/ជំនួយ":
        await help_command(update, context)
    else:
        # Normal AI chat
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        reply = await get_ai_response(chat_id, text)

        if reply is None:
            reply = "⚠️ No response from AI."
        else:
            reply = str(reply)

        await send_long_message(update, reply)

# ================= 6. MAIN EXECUTION =================

if __name__ == '__main__':
    if keep_alive:
        keep_alive()

    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

        # Commands
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('help', help_command))
        app.add_handler(CommandHandler('menu', menu_command))
        app.add_handler(CommandHandler('mode', mode_command))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))

        # Text messages (non-command)
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

        # Job queue (scheduled messages)
        jq = app.job_queue
        # កំណត់ម៉ោងជាទម្រង់ server time (ភាគច្រើន = UTC)
        # បើបងចង់ឱ្យត្រូវពេលកម្ពុជា អាចលៃតម្រូវម៉ោងនេះឲ្យបូក/ដក 7 ម៉ោងតាមតម្រូវការ។
        jq.run_daily(
            send_scheduled_alert,
            time=time(1, 0),
            data="☀️ អរុណសួស្តី! Good Morning!",
            name="morning"
        )
        jq.run_daily(
            send_scheduled_alert,
            time=time(6, 0),
            data="☕ ទិវាសួស្តី! Good Afternoon!",
            name="afternoon"
        )
        jq.run_daily(
            send_scheduled_alert,
            time=time(13, 0),
            data="🌙 រាត្រីសួស្តី! Good Evening!",
            name="evening"
        )

        print("✅ Bot is running with Scheduler...")
        app.run_polling(drop_pending_updates=True)
