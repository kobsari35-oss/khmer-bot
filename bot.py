import os
import logging
import json
import asyncio
from dotenv import load_dotenv

# Import សម្រាប់ Voice និង Web Server
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq
from keep_alive import keep_alive  # <--- ហៅមុខងារកុំឱ្យ Bot ដេកលក់

# ================= 1. CONFIGURATION =================
load_dotenv()

# ចំណាំ៖ ពេលដាក់លើ Render យើងនឹងមិនប្រើ .env ទេ តែប្រើ Environment Variables របស់ Render វិញ
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
GROQ_MODEL_AUDIO = "whisper-large-v3"
USERS_FILE = "users.json"

# បង្កើត Groq Client (ដាក់លក្ខខណ្ឌការពារ Error ពេលមិនទាន់ដាក់ Key)
if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    client = None

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ================= 2. PROMPTS =================

PROMPT_CONVERSATION = """
You are an expert Trilingual Conversation Tutor.

INSTRUCTIONS:
1. **Correction:** Correct grammar mistakes.
2. **Pronunciation (CRITICAL):** 
   - For **English**, write the **SOUND** using Khmer letters. (Ex: "Morning" -> "ម៉ូនីង")
   - For **Chinese**, write the **SOUND** using Khmer letters. (Ex: "Ni hao" -> "នី ហាវ")

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

# ================= 3. FUNCTIONS =================
def load_users():
    if not os.path.exists(USERS_FILE): return set()
    with open(USERS_FILE, 'r') as f:
        try: return set(json.load(f))
        except: return set()

def save_user(chat_id):
    # នៅលើ Render Free Tier, file នេះនឹងបាត់រាល់ពេល restart
    # ប៉ុន្តែវាមិនអីទេសម្រាប់ការចាប់ផ្តើម
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
        return "⚠️ មានបញ្ហាបច្ចេកទេសក្នុងការតភ្ជាប់ AI។"

# ================= 4. VOICE HANDLER =================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_chat.id)
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    try:
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        file_name = f"voice_{chat_id}.ogg"
        await voice_file.download_to_drive(file_name)

        if not client:
            await update.message.reply_text("❌ Missing Groq API Key")
            return

        with open(file_name, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(file_name, file.read()),
                model=GROQ_MODEL_AUDIO,
                response_format="text"
            )
        
        user_spoken_text = transcription
        # លុប file សំឡេងចោល
        if os.path.exists(file_name):
            os.remove(file_name)

        await update.message.reply_text(f"🎤 **ឮថា:** _{user_spoken_text}_", parse_mode="Markdown")

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        ai_reply = await get_ai_response(PROMPT_CONVERSATION, user_spoken_text)
        await update.message.reply_text(ai_reply)

    except Exception as e:
        logging.error(f"Voice Error: {e}")
        await update.message.reply_text("⚠️ ស្តាប់មិនច្បាស់។ សូមព្យាយាមម្តងទៀត។")

# ================= 5. COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_chat.id)
    msg = (
        "សួស្តី! ខ្ញុំដំណើរការ 24/7 ហើយ! 🚀\n"
        "👉 ផ្ញើ Voice ឬ អក្សរ ដើម្បីបកប្រែ។\n"
        "👉 ចុចប៊ូតុងខាងក្រោមដើម្បីរៀន។"
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def vocab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_chat.id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    reply = await get_ai_response(PROMPT_VOCAB, "Generate vocabulary list.")
    await update.message.reply_text(reply)

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    if not msg:
        await update.message.reply_text("⚠️ សូមវាយ៖ `/feedback សាររបស់អ្នក`")
        return
    if ADMIN_ID:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"📩 **Feedback:**\n{msg}")
        await update.message.reply_text("✅ បានផ្ញើហើយ!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👉 ខ្ញុំជា Bot បកប្រែ ៣ ភាសា។", reply_markup=get_main_keyboard())

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != ADMIN_ID: return
    msg = ' '.join(context.args)
    users = load_users()
    await update.message.reply_text(f"📢 Sending to {len(users)} users...")
    for uid in users:
        try: await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
        except: continue

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📚 រៀន Vocab": await vocab(update, context)
    elif text == "📩 Feedback": await update.message.reply_text("វាយ៖ `/feedback សារ`", parse_mode='Markdown')
    elif text == "❓ ជំនួយ": await help_command(update, context)
    else:
        save_user(update.effective_chat.id)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        reply = await get_ai_response(PROMPT_CONVERSATION, text)
        await update.message.reply_text(reply)

# ================= 6. MAIN RUN =================
if __name__ == '__main__':
    # 1. ចាប់ផ្តើម Web Server (សំខាន់សម្រាប់ Render)
    keep_alive()
    
    # 2. ពិនិត្យ Token
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
        
        print("✅ Bot is running on Cloud...")

        app.run_polling(drop_pending_updates=True)
