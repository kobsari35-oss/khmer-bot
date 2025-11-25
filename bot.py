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

# ព្យាយាម Import keep_alive សម្រាប់ Replit (បើមិនប្រើ Replit វានឹងរំលង)
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

# Global variable to store user preference
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

# ================= 2. PROMPTS (DUAL MODES) =================

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
    """Load user IDs from JSON file"""
    if not os.path.exists(USERS_FILE): return set()
    with open(USERS_FILE, 'r') as f:
        try: return set(json.load(f))
        except: return set()

def save_user_to_file(chat_id):
    """Save new user ID to JSON file"""
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        with open(USERS_FILE, 'w') as f: json.dump(list(users), f)

def get_main_keyboard():
    """Main Menu Keyboard"""
    keyboard = [
        [KeyboardButton("🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳"), KeyboardButton("🇺🇸 -> 🇰🇭 (Foreigner)")],
        [KeyboardButton("📩 Feedback"), KeyboardButton("❓ Help/ជំនួយ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def get_ai_response(chat_id, user_text):
    """Fetch response from Groq AI"""
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

# ================= 4. SCHEDULING ALERT (ALARM) =================

async def send_scheduled_alert(context: ContextTypes.DEFAULT_TYPE):
    """Sends automatic messages to all users"""
    message = context.job.data
    users = load_users()
    
    print(f"⏰ Auto-Sending Alert: {message}")
    
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
        except Exception as e:
            # User might have blocked the bot
            pass

# ================= 5. COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user_to_file(chat_id)
    
    if chat_id not in USER_MODES: 
        USER_MODES[chat_id] = 'learner'

    msg = (f"Hello {user.first_name}! 👋\n\n"
           "Please choose your mode:\n"
           "1. 🇰🇭 **Khmer Learner**: Learn English/Chinese.\n"
           "2. 🇺🇸 **Foreigner**: Learn Khmer.")
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    if not msg:
        await update.message.reply_text("⚠️ Usage: `/feedback [your message]`")
        return
    
    if ADMIN_ID:
        try:
            await context.bot.send_message(chat_id=int(ADMIN_ID), text=f"📩 Feedback from {update.effective_user.first_name}: {msg}")
            await update.message.reply_text("✅ Feedback sent to Admin.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error sending feedback: {e}")
    else:
        await update.message.reply_text("⚠️ Admin ID not set.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only Admin can use this
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID): 
        return
    
    msg = ' '.join(context.args)
    if not msg:
        await update.message.reply_text("⚠️ Usage: `/broadcast [message]`")
        return

    users = load_users()
    count = 0
    for uid in users:
        try: 
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
            count += 1
        except: continue
    
    await update.message.reply_text(f"✅ Broadcast sent to {count} users.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # Handle Menu Buttons
    if text == "🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳":
        USER_MODES[chat_id] = 'learner'
        await update.message.reply_text("✅ **Mode: Khmer Learner** set.")
    
    elif text == "🇺🇸 -> 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = 'foreigner'
        await update.message.reply_text("✅ **Mode: Foreigner Standard** set.")
    
    elif text == "📩 Feedback": 
        await update.message.reply_text("Type: `/feedback [message]`")
    
    elif text == "❓ Help/ជំនួយ": 
        await start(update, context)
    
    else:
        # Handle AI Chat
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        reply = await get_ai_response(chat_id, text)
        await update.message.reply_text(reply)

# ================= 6. MAIN EXECUTION =================

if __name__ == '__main__':
    # Start Web Server for Replit (Optional)
    if keep_alive:
        keep_alive()

    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_TOKEN is missing in .env file.")
        exit()

    # Build Application
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Add Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('feedback', feedback_command))
    app.add_handler(CommandHandler('broadcast', broadcast))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # --- SCHEDULING (TIME IN UTC) ---
    # Note: Cambodia is UTC+7. 
    # To set 8:00 AM Cambodia time, we use 1:00 AM UTC (8 - 7 = 1).
    
    job_queue = app.job_queue

    # 1. Morning Alert (8:00 AM KH -> 1:00 AM UTC)
    job_queue.run_daily(
        send_scheduled_alert, 
        time=time(1, 0), 
        data="☀️ អរុណសួស្តី! ថ្ងៃថ្មីហើយ កុំភ្លេចរៀនពាក្យអង់គ្លេសថ្មីៗមួយថ្ងៃ ៥ ពាក្យណា៎!",
        name="morning_alert"
    )

    # 2. Afternoon Alert (1:00 PM KH -> 6:00 AM UTC)
    job_queue.run_daily(
        send_scheduled_alert, 
        time=time(6, 0), 
        data="☕ ទិវាសួស្តី! ញ៉ាំបាយហើយឬនៅ? ឆ្លៀតពេលរៀនបន្តិចទៀតណា។",
        name="afternoon_alert"
    )

    # 3. Evening Alert (8:00 PM KH -> 1:00 PM UTC)
    job_queue.run_daily(
        send_scheduled_alert, 
        time=time(13, 0), 
        data="🌙 រាត្រីសួស្តី! ដល់ម៉ោងសម្រាកហើយ។ Good Night!",
        name="evening_alert"
    )

    print("✅ Bot is running with Scheduler...")
    app.run_polling(drop_pending_updates=True)
