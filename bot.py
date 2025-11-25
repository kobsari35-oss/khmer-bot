import os
import logging
import json
import asyncio
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq
from keep_alive import keep_alive

# ================= 1. CONFIGURATION =================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
USERS_FILE = "users.json"

# 🔥 ទុកចំណាំថាអ្នកប្រើប្រាស់ម្នាក់ៗកំពុងស្ថិតក្នុង Mode មួយណា
# 'learner' = ខ្មែររៀនអង់គ្លេស (Default)
# 'foreigner' = បរទេសរៀនខ្មែរ
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

# 🟢 MODE 1: សម្រាប់ខ្មែររៀនអង់គ្លេស/ចិន (KHMER LEARNER)
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
🗣️ **អានថា:** [SOUND IN KHMER LETTERS (Ex: I go -> អាយ ហ្គោ)]
--------------------------------
🇨🇳 **Chinese:** [Text] ([Pinyin])
🗣️ **អានថា:** [SOUND IN KHMER LETTERS]
--------------------------------
🇰🇭 **ប្រែថា:** [Khmer Meaning]
--------------------------------
📝 **ឧទាហរណ៍:** [Example sentence in 3 languages]
--------------------------------
💡 **ពន្យល់:** [Grammar explanation in Khmer]
"""

# 🔵 MODE 2: សម្រាប់ជនបរទេសរៀនខ្មែរ (FOREIGNER STANDARD)
PROMPT_FOREIGNER = """
You are a Khmer Language & Cultural Guide for Foreigners.

YOUR TASK:
1. Translate English/Chinese input into **Standard Polite Khmer**.
2. Provide **Romanized Phonetics** (English letters) so the foreigner can pronounce it easily.
3. Provide a Cultural Tip (politeness, gender particles like 'Bat/Jah').

OUTPUT FORMAT:
--------------------------------
🇰🇭 **Khmer Script:** [Writing in Khmer]
🗣️ **Say:** [Romanized Phonetics (Ex: Sous-dey)]
📖 **Meaning:** [Literal meaning if needed]
--------------------------------
📝 **Example:**
[Simple sentence usage]
--------------------------------
💡 **Cultural Tip:** [Explain usage: polite/casual, 'Bong', 'Oun', 'Bat/Jah']
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
    
    # ឆែកមើលថាអ្នកប្រើប្រាស់ស្ថិតក្នុង Mode ណា (Default = learner)
    mode = USER_MODES.get(chat_id, 'learner')
    
    if mode == 'foreigner':
        system_prompt = PROMPT_FOREIGNER
    else:
        system_prompt = PROMPT_KHMER_LEARNER

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

# ================= 4. COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    save_user_to_file(chat_id)
    
    # Set default mode
    if chat_id not in USER_MODES:
        USER_MODES[chat_id] = 'learner'

    msg = (
        f"Hello {user.first_name}! 👋\n"
        f"សូមជ្រើសរើស Mode របស់អ្នក / Please choose your mode:\n\n"
        f"1️⃣ **🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳**: សម្រាប់ខ្មែររៀនអង់គ្លេស/ចិន (Grammar & Pronunciation)។\n"
        f"2️⃣ **🇺🇸 -> 🇰🇭 (Foreigner)**: For foreigners visiting Cambodia (Learn to speak Khmer)."
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    if not msg:
        await update.message.reply_text("⚠️ ប្រើ/Usage: `/feedback [msg]`")
        return
    if ADMIN_ID:
        await context.bot.send_message(chat_id=int(ADMIN_ID), text=f"📩 Feedback: {msg}")
        await update.message.reply_text("✅ Sent/បានផ្ញើ។")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID): return
    msg = ' '.join(context.args)
    users = load_users()
    for uid in users:
        try: await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
        except: continue

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # --- BUTTON LOGIC ---
    if text == "🇰🇭 ខ្មែរ -> 🇺🇸🇨🇳":
        USER_MODES[chat_id] = 'learner'
        await update.message.reply_text("✅ **Mode: Khmer Learner**\nសរសេរអង់គ្លេសមក ខ្ញុំនឹងកែ Grammar និងប្រាប់របៀបអានជាអក្សរខ្មែរ។")
    
    elif text == "🇺🇸 -> 🇰🇭 (Foreigner)":
        USER_MODES[chat_id] = 'foreigner'
        await update.message.reply_text("✅ **Mode: Foreigner Standard**\nType English, and I will translate to Khmer with Romanized phonetics for you!")
    
    elif text == "📩 Feedback": 
        await update.message.reply_text("Type: `/feedback [message]`", parse_mode='Markdown')
    
    elif text == "❓ Help/ជំនួយ": 
        await start(update, context)
    
    else:
        # --- AI PROCESSING ---
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        reply = await get_ai_response(chat_id, text)
        await update.message.reply_text(reply)

# ================= 5. RUN =================
if __name__ == '__main__':
    keep_alive()
    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        print("✅ Bot (Dual Mode: Khmer & Foreigner) is running...")
        app.run_polling(drop_pending_updates=True)
