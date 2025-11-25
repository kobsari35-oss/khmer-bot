import os
import logging
import json
import asyncio
from datetime import time
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq

# Import មុខងារ Keep Alive ពី file ផ្សេង
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

# ================= 2. PROMPTS =================

PROMPT_KHMER_LEARNER = """
You are an expert Language Tutor for Khmer speakers.
YOUR TASK:
1. Correct Grammar (English/Chinese).
2. Provide Phonetics in KHMER SCRIPT.
3. Provide Translation in Khmer.
4. Provide a Usage Example.

OUTPUT FORMAT:
--------------------------------
✅ **Corrected:** [Correct Sentence]
🗣️ **អានថា:** [SOUND IN KHMER LETTERS]
--------------------------------
🇰🇭 **ប្រែថា:** [Khmer Meaning]
--------------------------------
📝 **ឧទាហរណ៍:** [Example sentence]
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
    if not os.path.exists(USERS_FILE): return set()
    with open(USERS_FILE, 'r') as f:
        try: return set(json.load(f))
        except: return set()

def save_user_to_file(chat_id):
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        with open(USERS_FILE, 'w') as f: json.dump(list(users), f)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳"), KeyboardButton("🇺🇸 -> 🇰🇭 (Foreigner)")],
        [KeyboardButton("📩 Feedback"), KeyboardButton("❓ Help/ជំនួយ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def get_ai_response(chat_id, user_text):
    if not client: return "⚠️ Server Error: Missing API Key."
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
        logging.error(f"AI Chat Error: {e}")
        return "⚠️ Error connecting to AI."

# ================= 4. SCHEDULING ALERT =================

async def send_scheduled_alert(context: ContextTypes.DEFAULT_TYPE):
    """Sends automatic messages to all users"""
    message = context.job.data
    users = load_users()
    print(f"⏰ Auto-Sending Alert: {message}")
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
        except:
            pass

# ================= 5. HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user_to_file(chat_id)
    if chat_id not in USER_MODES: USER_MODES[chat_id] = 'learner'

    msg = (f"Hello {user.first_name}! 👋\nWelcome to AI Language Bot.")
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    if ADMIN_ID and msg:
        await context.bot.send_message(chat_id=int(ADMIN_ID), text=f"📩 Feedback: {msg}")
        await update.message.reply_text("✅ Feedback sent.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID): return
    msg = ' '.join(context.args)
    users = load_users()
    for uid in users:
        try: await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
        except: continue
    await update.message.reply_text("✅ Broadcast sent.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳":
        USER_MODES[chat_id] = 'learner'
        await update.message.reply_text("✅ Mode: Khmer Learner")
    elif text == "🇺🇸 -> 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = 'foreigner'
        await update.message.reply_text("✅ Mode: Foreigner Standard")
    elif text == "📩 Feedback": 
        await update.message.reply_text("Type: `/feedback [msg]`")
    elif text == "❓ Help/ជំនួយ": 
        await start(update, context)
    else:
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        reply = await get_ai_response(chat_id, text)
        await update.message.reply_text(reply)

# ================= 6. MAIN EXECUTION =================

if __name__ == '__main__':
    # 1. ដំណើរការ Web Server (កុំឱ្យ Render បិទ)
    if keep_alive:
        keep_alive()

    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        # Add Handlers
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        # Schedule Jobs (UTC TIME)
        # Cambodia is UTC+7. So we subtract 7 hours from desired KH time.
        jq = app.job_queue
        
        # 8:00 AM KH = 1:00 AM UTC
        jq.run_daily(send_scheduled_alert, time=time(1, 0), data="☀️ អរុណសួស្តី! Good Morning!", name="morning")
        
        # 1:00 PM KH = 6:00 AM UTC
        jq.run_daily(send_scheduled_alert, time=time(6, 0), data="☕ ទិវាសួស្តី! Good Afternoon!", name="afternoon")
        
        # 8:00 PM KH = 1:00 PM UTC
        jq.run_daily(send_scheduled_alert, time=time(13, 0), data="🌙 រាត្រីសួស្តី! Good Evening!", name="evening")

        print("✅ Bot is running with Scheduler...")
        app.run_polling(drop_pending_updates=True)import os
import logging
import json
import asyncio
from datetime import time
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq

# Import មុខងារ Keep Alive ពី file ផ្សេង
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

# ================= 2. PROMPTS =================

PROMPT_KHMER_LEARNER = """
You are an expert Language Tutor for Khmer speakers.
YOUR TASK:
1. Correct Grammar (English/Chinese).
2. Provide Phonetics in KHMER SCRIPT.
3. Provide Translation in Khmer.
4. Provide a Usage Example.

OUTPUT FORMAT:
--------------------------------
✅ **Corrected:** [Correct Sentence]
🗣️ **អានថា:** [SOUND IN KHMER LETTERS]
--------------------------------
🇰🇭 **ប្រែថា:** [Khmer Meaning]
--------------------------------
📝 **ឧទាហរណ៍:** [Example sentence]
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
    if not os.path.exists(USERS_FILE): return set()
    with open(USERS_FILE, 'r') as f:
        try: return set(json.load(f))
        except: return set()

def save_user_to_file(chat_id):
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        with open(USERS_FILE, 'w') as f: json.dump(list(users), f)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳"), KeyboardButton("🇺🇸 -> 🇰🇭 (Foreigner)")],
        [KeyboardButton("📩 Feedback"), KeyboardButton("❓ Help/ជំនួយ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def get_ai_response(chat_id, user_text):
    if not client: return "⚠️ Server Error: Missing API Key."
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
        logging.error(f"AI Chat Error: {e}")
        return "⚠️ Error connecting to AI."

# ================= 4. SCHEDULING ALERT =================

async def send_scheduled_alert(context: ContextTypes.DEFAULT_TYPE):
    """Sends automatic messages to all users"""
    message = context.job.data
    users = load_users()
    print(f"⏰ Auto-Sending Alert: {message}")
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
        except:
            pass

# ================= 5. HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user_to_file(chat_id)
    if chat_id not in USER_MODES: USER_MODES[chat_id] = 'learner'

    msg = (f"Hello {user.first_name}! 👋\nWelcome to AI Language Bot.")
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    if ADMIN_ID and msg:
        await context.bot.send_message(chat_id=int(ADMIN_ID), text=f"📩 Feedback: {msg}")
        await update.message.reply_text("✅ Feedback sent.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID): return
    msg = ' '.join(context.args)
    users = load_users()
    for uid in users:
        try: await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
        except: continue
    await update.message.reply_text("✅ Broadcast sent.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳":
        USER_MODES[chat_id] = 'learner'
        await update.message.reply_text("✅ Mode: Khmer Learner")
    elif text == "🇺🇸 -> 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = 'foreigner'
        await update.message.reply_text("✅ Mode: Foreigner Standard")
    elif text == "📩 Feedback": 
        await update.message.reply_text("Type: `/feedback [msg]`")
    elif text == "❓ Help/ជំនួយ": 
        await start(update, context)
    else:
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        reply = await get_ai_response(chat_id, text)
        await update.message.reply_text(reply)

# ================= 6. MAIN EXECUTION =================

if __name__ == '__main__':
    # 1. ដំណើរការ Web Server (កុំឱ្យ Render បិទ)
    if keep_alive:
        keep_alive()

    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        # Add Handlers
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        # Schedule Jobs (UTC TIME)
        # Cambodia is UTC+7. So we subtract 7 hours from desired KH time.
        jq = app.job_queue
        
        # 8:00 AM KH = 1:00 AM UTC
        jq.run_daily(send_scheduled_alert, time=time(1, 0), data="☀️ អរុណសួស្តី! Good Morning!", name="morning")
        
        # 1:00 PM KH = 6:00 AM UTC
        jq.run_daily(send_scheduled_alert, time=time(6, 0), data="☕ ទិវាសួស្តី! Good Afternoon!", name="afternoon")
        
        # 8:00 PM KH = 1:00 PM UTC
        jq.run_daily(send_scheduled_alert, time=time(13, 0), data="🌙 រាត្រីសួស្តី! Good Evening!", name="evening")

        print("✅ Bot is running with Scheduler...")
        app.run_polling(drop_pending_updates=True)import os
import logging
import json
import asyncio
from datetime import time
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq

# Import មុខងារ Keep Alive ពី file ផ្សេង
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

# ================= 2. PROMPTS =================

PROMPT_KHMER_LEARNER = """
You are an expert Language Tutor for Khmer speakers.
YOUR TASK:
1. Correct Grammar (English/Chinese).
2. Provide Phonetics in KHMER SCRIPT.
3. Provide Translation in Khmer.
4. Provide a Usage Example.

OUTPUT FORMAT:
--------------------------------
✅ **Corrected:** [Correct Sentence]
🗣️ **អានថា:** [SOUND IN KHMER LETTERS]
--------------------------------
🇰🇭 **ប្រែថា:** [Khmer Meaning]
--------------------------------
📝 **ឧទាហរណ៍:** [Example sentence]
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
    if not os.path.exists(USERS_FILE): return set()
    with open(USERS_FILE, 'r') as f:
        try: return set(json.load(f))
        except: return set()

def save_user_to_file(chat_id):
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        with open(USERS_FILE, 'w') as f: json.dump(list(users), f)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳"), KeyboardButton("🇺🇸 -> 🇰🇭 (Foreigner)")],
        [KeyboardButton("📩 Feedback"), KeyboardButton("❓ Help/ជំនួយ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def get_ai_response(chat_id, user_text):
    if not client: return "⚠️ Server Error: Missing API Key."
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
        logging.error(f"AI Chat Error: {e}")
        return "⚠️ Error connecting to AI."

# ================= 4. SCHEDULING ALERT =================

async def send_scheduled_alert(context: ContextTypes.DEFAULT_TYPE):
    """Sends automatic messages to all users"""
    message = context.job.data
    users = load_users()
    print(f"⏰ Auto-Sending Alert: {message}")
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
        except:
            pass

# ================= 5. HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user_to_file(chat_id)
    if chat_id not in USER_MODES: USER_MODES[chat_id] = 'learner'

    msg = (f"Hello {user.first_name}! 👋\nWelcome to AI Language Bot.")
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    if ADMIN_ID and msg:
        await context.bot.send_message(chat_id=int(ADMIN_ID), text=f"📩 Feedback: {msg}")
        await update.message.reply_text("✅ Feedback sent.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID): return
    msg = ' '.join(context.args)
    users = load_users()
    for uid in users:
        try: await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
        except: continue
    await update.message.reply_text("✅ Broadcast sent.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳":
        USER_MODES[chat_id] = 'learner'
        await update.message.reply_text("✅ Mode: Khmer Learner")
    elif text == "🇺🇸 -> 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = 'foreigner'
        await update.message.reply_text("✅ Mode: Foreigner Standard")
    elif text == "📩 Feedback": 
        await update.message.reply_text("Type: `/feedback [msg]`")
    elif text == "❓ Help/ជំនួយ": 
        await start(update, context)
    else:
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        reply = await get_ai_response(chat_id, text)
        await update.message.reply_text(reply)

# ================= 6. MAIN EXECUTION =================

if __name__ == '__main__':
    # 1. ដំណើរការ Web Server (កុំឱ្យ Render បិទ)
    if keep_alive:
        keep_alive()

    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        # Add Handlers
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        # Schedule Jobs (UTC TIME)
        # Cambodia is UTC+7. So we subtract 7 hours from desired KH time.
        jq = app.job_queue
        
        # 8:00 AM KH = 1:00 AM UTC
        jq.run_daily(send_scheduled_alert, time=time(1, 0), data="☀️ អរុណសួស្តី! Good Morning!", name="morning")
        
        # 1:00 PM KH = 6:00 AM UTC
        jq.run_daily(send_scheduled_alert, time=time(6, 0), data="☕ ទិវាសួស្តី! Good Afternoon!", name="afternoon")
        
        # 8:00 PM KH = 1:00 PM UTC
        jq.run_daily(send_scheduled_alert, time=time(13, 0), data="🌙 រាត្រីសួស្តី! Good Evening!", name="evening")

        print("✅ Bot is running with Scheduler...")
        app.run_polling(drop_pending_updates=True)
