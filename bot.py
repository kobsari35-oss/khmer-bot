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
        await update.message.reply_text("✅ **Mode: Khmer Learner**\nសរសេរមកបាន! ខ្ញុំនឹងចេញទាំង អង់គ្លេស និង ចិន។", parse_mode=ParseMode.MARKDOWN)
    elif text == "🇺🇸 -> 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = 'foreigner'
        await update.message.reply_text("✅ **Mode: Foreigner Standard**", parse_mode=ParseMode.MARKDOWN)
    elif text == "📩 Feedback": 
        await update.message.reply_text("Type: `/feedback [msg]`", parse_mode=ParseMode.MARKDOWN)
    elif text == "❓ Help/ជំនួយ": 
        await start(update, context)
    else:
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        reply = await get_ai_response(chat_id, text)
        await update.message.reply_text(reply)

# ================= 6. MAIN EXECUTION =================

if __name__ == '__main__':
    # កុំខ្វល់ពី Error លើ Windows, លើ Render វានឹងដំណើរការ
    if keep_alive:
        keep_alive()

    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        jq = app.job_queue
        # Schedule Times (UTC)
        jq.run_daily(send_scheduled_alert, time=time(1, 0), data="☀️ អរុណសួស្តី! Good Morning!", name="morning")
        jq.run_daily(send_scheduled_alert, time=time(6, 0), data="☕ ទិវាសួស្តី! Good Afternoon!", name="afternoon")
        jq.run_daily(send_scheduled_alert, time=time(13, 0), data="🌙 រាត្រីសួស្តី! Good Evening!", name="evening")

        print("✅ Bot is running with Scheduler...")
        app.run_polling(drop_pending_updates=True)
