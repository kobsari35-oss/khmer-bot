import os
import logging
import json
import asyncio
from dotenv import load_dotenv

# Import សម្រាប់ Voice, Web Server & Formatting
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq
# ត្រូវប្រាកដថាអ្នកមាន file keep_alive.py នៅក្នុង Folder ដែរ
from keep_alive import keep_alive

# ================= 1. CONFIGURATION =================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

# Model Configuration
GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
GROQ_MODEL_AUDIO = "whisper-large-v3"
USERS_FILE = "users.json"

# Setup Groq Client
if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    client = None
    print("⚠️ Warning: GROQ_API_KEY is missing!")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ================= 2. PROMPTS (SMART AI) =================

PROMPT_CONVERSATION = """
You are an expert Trilingual Translator and Tutor (Khmer, English, Chinese).

CRITICAL INSTRUCTIONS:
1. **ACCURACY IS PRIORITY:** You must translate the **exact meaning**.
   - Ex: "ស្អែក" = "Tomorrow" (NOT Frog).
   - Ex: "ខ្ញុំឃ្លាន" = "I am hungry".
2. **PRONUNCIATION:** 
   - For **English**, write the **SOUND** using Khmer letters. (Ex: "Tomorrow" -> "ធូម៉ូរ៉ូ")
   - For **Chinese**, write the **SOUND** using Khmer letters. (Ex: "Míngtiān" -> "មីង ធាន")

OUTPUT FORMAT:
🇺🇸 **English:** [Text]
🗣️ **អានថា:** [English Sound in Khmer]
🇨🇳 **Chinese:** [Text] ([Pinyin])
🗣️ **អានថា:** [Chinese Sound in Khmer]
🇰🇭 **Khmer:** [Translation]
💡 **Grammar:** [Note]
"""

PROMPT_VOCAB = """
Generate 5 useful vocabulary words related to a random daily topic.
STRICT OUTPUT FORMAT PER WORD:
[Number]. 🇺🇸 [English Word]
🗣️ [Write the ENGLISH SOUND using Khmer script]
🇨🇳 [Chinese Word] ([Pinyin])
🇰🇭 [Khmer Meaning]
Do not add extra notes. Just the list.
"""

# ================= 3. HELPER FUNCTIONS =================
def load_users():
    if not os.path.exists(USERS_FILE): return set()
    with open(USERS_FILE, 'r') as f:
        try: return set(json.load(f))
        except: return set()

def save_user_to_file(chat_id):
    """Save User ID to file"""
    users = load_users()
    if chat_id not in users:
        users.add(chat_id)
        with open(USERS_FILE, 'w') as f: json.dump(list(users), f)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📚 រៀន Vocab"), KeyboardButton("📩 Feedback")],
        [KeyboardButton("❓ ជំនួយ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def get_ai_response(system_prompt, user_text):
    if not client: return "⚠️ Server Error: Missing API Key."
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            model=GROQ_MODEL_CHAT,
            temperature=0.3,
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"AI Chat Error: {e}")
        return "⚠️ មានបញ្ហាបច្ចេកទេស។"

# ================= 4. COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 1. ពិនិត្យមើល User ថ្មី
    current_users = load_users()
    
    if chat_id not in current_users:
        # === Admin Alert Logic ===
        full_name = user.full_name
        username = f"@{user.username}" if user.username else "❌ No Username"
        
        admin_alert = (
            f"🚨 **New User Joined!** 🚨\n\n"
            f"👤 **Name:** {full_name}\n"
            f"🆔 **Username:** {username}\n"
            f"🔢 **ID:** `{chat_id}`"
        )
        
        # ផ្ញើទៅ Admin (Convert ID to int for safety)
        if ADMIN_ID:
            try:
                await context.bot.send_message(chat_id=int(ADMIN_ID), text=admin_alert, parse_mode='Markdown')
            except Exception as e:
                logging.error(f"Failed to notify admin: {e}")
        
        # Save User
        save_user_to_file(chat_id)

    # 2. សារស្វាគមន៍
    msg = (
        f"សួស្តី {user.first_name}! ស្វាគមន៍មកកាន់ Bot ៣ ភាសា 🎙️\n\n"
        "👉 ផ្ញើ Voice ឬ អក្សរ ដើម្បីបកប្រែ។\n"
        "👉 ចុចប៊ូតុងខាងក្រោមដើម្បីរៀន។"
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def vocab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user_to_file(update.effective_chat.id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    reply = await get_ai_response(PROMPT_VOCAB, "Generate vocabulary list.")
    await update.message.reply_text(reply)

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    user = update.effective_user
    if not msg:
        await update.message.reply_text("⚠️ សូមវាយ៖ `/feedback [សាររបស់អ្នក]`")
        return
    if ADMIN_ID:
        info = f"@{user.username}" if user.username else f"{user.first_name}"
        try:
            await context.bot.send_message(chat_id=int(ADMIN_ID), text=f"📩 **Feedback from {info}:**\n{msg}")
            await update.message.reply_text("✅ បានផ្ញើជូន Admin ហើយ!")
        except:
            await update.message.reply_text("❌ មិនអាចផ្ញើបាន។")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👉 ខ្ញុំជា Bot បកប្រែ ៣ ភាសា (ខ្មែរ-អង់គ្លេស-ចិន)។", reply_markup=get_main_keyboard())

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check Admin ID
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID):
        return
    
    msg = ' '.join(context.args)
    if not msg:
        await update.message.reply_text("⚠️ សូមសរសេរសារ។ ឧ: /broadcast hello")
        return

    users = load_users()
    await update.message.reply_text(f"📢 កំពុងផ្ញើទៅកាន់ {len(users)} នាក់...")
    
    count = 0
    for uid in users:
        try: 
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
            count += 1
            await asyncio.sleep(0.05) # Anti-spam delay
        except: 
            continue
    await update.message.reply_text(f"✅ បានផ្ញើជោគជ័យទៅកាន់ {count} នាក់។")

# ================= 5. MESSAGE HANDLERS =================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user_to_file(update.effective_chat.id)
    chat_id = update.effective_chat.id
    file_name = f"voice_{chat_id}.ogg"

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    try:
        # Download
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        await voice_file.download_to_drive(file_name)

        if not client: 
            await update.message.reply_text("❌ API Key Missing.")
            return

        # Transcribe
        with open(file_name, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(file_name, file.read()),
                model=GROQ_MODEL_AUDIO,
                response_format="text"
            )
        
        user_spoken_text = transcription
        
        # Reply Text
        await update.message.reply_text(f"🎤 **ឮថា:** _{user_spoken_text}_", parse_mode="Markdown")
        
        # Translate
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        ai_reply = await get_ai_response(PROMPT_CONVERSATION, user_spoken_text)
        await update.message.reply_text(ai_reply)

    except Exception as e:
        logging.error(f"Voice Error: {e}")
        await update.message.reply_text("⚠️ ស្តាប់មិនច្បាស់ ឬមានបញ្ហា។")
    
    finally:
        # Clean up file (Always remove file even if error)
        if os.path.exists(file_name):
            os.remove(file_name)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📚 រៀន Vocab": await vocab(update, context)
    elif text == "📩 Feedback": await update.message.reply_text("វាយ៖ `/feedback សារ`", parse_mode='Markdown')
    elif text == "❓ ជំនួយ": await help_command(update, context)
    else:
        save_user_to_file(update.effective_chat.id)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        reply = await get_ai_response(PROMPT_CONVERSATION, text)
        await update.message.reply_text(reply)

# ================= 6. MAIN RUN =================
if __name__ == '__main__':
    # 1. Start Web Server for Render
    keep_alive()
    
    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN is missing.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('vocab', vocab))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))
        app.add_handler(MessageHandler(filters.VOICE, handle_voice))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        print("✅ Bot is running on Cloud (Auto-Deploy)...")
        
        # 2. Run Bot with CLEAN START (drop_pending_updates=True)
        # នេះជាចំណុចសំខាន់ដើម្បីការពារ Conflict
        app.run_polling(drop_pending_updates=True)