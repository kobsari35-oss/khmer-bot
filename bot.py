import os
import logging
import json
import asyncio
import re
from io import BytesIO
from dotenv import load_dotenv

# Import សម្រាប់ Voice, Web Server & Formatting
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import Groq
from gtts import gTTS 
from keep_alive import keep_alive

# ================= 1. CONFIGURATION =================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

# Username Admin (មាន \ ដើម្បីកុំឱ្យខូច Link)
ADMIN_USERNAME = "@Samross\_Ph\_Care"

GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
GROQ_MODEL_AUDIO = "whisper-large-v3"
USERS_FILE = "users.json"

if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    client = None
    print("⚠️ Warning: GROQ_API_KEY is missing!")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ================= 2. PROMPTS (SMARTER AI) =================

# 🔥 UPDATE: បន្ថែមឱ្យស្គាល់ Khmer Romanized / Slang
PROMPT_CONVERSATION = """
You are an expert Trilingual Translator (Khmer, English, Chinese).

CRITICAL INSTRUCTIONS:
1. **INPUT HANDLING:**
   - You MUST understand **Khmer Romanized / Khmernglish** (e.g., "nh tv" = "I go", "ot ei te" = "No problem", "sml" = "soup").
   - If the user uses slang or abbreviations (e.g., "u", "r", "b", "xd"), interpret them naturally.

2. **ACCURACY:** Translate the meaning into Standard English, Chinese, and Khmer Script.

3. **PRONUNCIATION:** 
   - For English & Chinese, write the sound using Khmer letters.

OUTPUT FORMAT:
🇺🇸 **English:** [Standard English]
🗣️ **អានថា:** [English Sound in Khmer]
🇨🇳 **Chinese:** [Text] ([Pinyin])
🗣️ **អានថា:** [Chinese Sound in Khmer]
🇰🇭 **Khmer:** [Standard Khmer Script Translation]
💡 **Grammar:** [Brief note on the original slang/grammar]
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

async def send_tts_audio(context, chat_id, text):
    try:
        match = re.search(r"🇺🇸 \*\*English:\*\*\s*(.+)", text)
        if match:
            english_text = match.group(1).strip()
            if len(english_text) < 2: return
            tts = gTTS(text=english_text, lang='en')
            audio_data = BytesIO()
            tts.write_to_fp(audio_data)
            audio_data.seek(0)
            await context.bot.send_voice(chat_id=chat_id, voice=audio_data)
    except Exception as e:
        logging.error(f"TTS Error: {e}")

# ================= 4. COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if chat_id not in load_users():
        # Admin Alert Fix
        if str(chat_id) != str(ADMIN_ID):
            full_name = user.full_name
            username = f"@{user.username}" if user.username else "No Username"
            admin_alert = f"🚨 **New User Joined!**\n👤 {full_name}\n🆔 {username}\n🔢 `{chat_id}`"
            if ADMIN_ID:
                try: await context.bot.send_message(chat_id=int(ADMIN_ID), text=admin_alert, parse_mode='Markdown')
                except: pass
        save_user_to_file(chat_id)

    # សារស្វាគមន៍ (Fixed Link)
    msg = (
        f"សួស្តី {user.first_name}! 👋\n"
        f"សូមស្វាគមន៍មកកាន់ **Bot ជំនួយការភាសា ៣ (ខ្មែរ-អង់គ្លេស-ចិន)** 🤖✨\n\n"
        f"ខ្ញុំអាចជួយអ្នកបកប្រែ (ស្គាល់ទាំងភាសា Chat/Khmernglish)។\n\n"
        f"🛠 **របៀបប្រើប្រាស់៖**\n"
        f"1️⃣ **និយាយ (Voice):** ចុចរូប 🎙️ និយាយហើយផ្ញើមក។\n"
        f"2️⃣ **សរសេរ (Text):** វាយអក្សរខ្មែរ អង់គ្លេស ឬ 'nh tv dae' ក៏បាន។\n"
        f"3️⃣ **រៀនពាក្យ:** ចុចប៊ូតុង \"📚 រៀន Vocab\"។\n\n"
        f"🆘 **ទាក់ទង Admin:**\n"
        f"• វាយ៖ `/feedback [សាររបស់អ្នក]`\n"
        f"• ឬឆាតទៅ៖ {ADMIN_USERNAME}"
    )
    
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def vocab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user_to_file(update.effective_chat.id)
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
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
    await start(update, context)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or str(update.effective_chat.id) != str(ADMIN_ID): return
    msg = ' '.join(context.args)
    users = load_users()
    await update.message.reply_text(f"📢 Sending to {len(users)} users...")
    for uid in users:
        try: 
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
            await asyncio.sleep(0.05)
        except: continue
    await update.message.reply_text("✅ Done.")

# ================= 5. HANDLERS =================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user_to_file(update.effective_chat.id)
    chat_id = update.effective_chat.id
    file_name = f"voice_{chat_id}.ogg"

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        await voice_file.download_to_drive(file_name)

        if not client: 
            await update.message.reply_text("❌ API Key Missing.")
            return

        with open(file_name, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(file_name, file.read()),
                model=GROQ_MODEL_AUDIO,
                response_format="text"
            )
        
        await update.message.reply_text(f"🎤 **ឮថា:** _{transcription}_", parse_mode="Markdown")
        
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        ai_reply = await get_ai_response(PROMPT_CONVERSATION, transcription)
        await update.message.reply_text(ai_reply)

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        await send_tts_audio(context, chat_id, ai_reply)

    except Exception as e:
        logging.error(f"Voice Error: {e}")
        await update.message.reply_text("⚠️ Error.")
    finally:
        if os.path.exists(file_name): os.remove(file_name)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "📚 រៀន Vocab": await vocab(update, context)
    elif text == "📩 Feedback": await update.message.reply_text("វាយ៖ `/feedback សារ`", parse_mode='Markdown')
    elif text == "❓ ជំនួយ": await help_command(update, context)
    else:
        save_user_to_file(chat_id)
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        # Translate
        reply = await get_ai_response(PROMPT_CONVERSATION, text)
        await update.message.reply_text(reply)

        # Speak
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        await send_tts_audio(context, chat_id, reply)

# ================= 6. RUN =================
if __name__ == '__main__':
    keep_alive()
    if TELEGRAM_TOKEN:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('vocab', vocab))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))
        app.add_handler(MessageHandler(filters.VOICE, handle_voice))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        print("✅ Bot is running (Supports Khmernglish)...")
        app.run_polling(drop_pending_updates=True)
