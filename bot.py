import os
import logging
import json
import asyncio
import re
from io import BytesIO
from dotenv import load_dotenv

# Import សម្រាប់ Voice, Web Server & Formatting
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from groq import AsyncGroq # 🔥 ប្រើ Async ដើម្បីកុំឱ្យ Bot គាំង
from gtts import gTTS 

# ព្យាយាម Import keep_alive ដោយមិនឱ្យ Error បើ Run លើកុំព្យូទ័រផ្ទាល់ខ្លួន
try:
    from keep_alive import keep_alive
except ImportError:
    def keep_alive():
        print("⚠️ keep_alive module not found. Web server not started.")

# ================= 1. CONFIGURATION =================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")
ADMIN_USERNAME = "@Samross_Ph_Care"  # មិនចាំបាច់ដាក់ \_ ទេ យើងនឹងកែពេលបង្ហាញ

GROQ_MODEL_CHAT = "llama-3.3-70b-versatile"
GROQ_MODEL_AUDIO = "whisper-large-v3"
USERS_FILE = "users.json"

# 🔥 កំណត់ Client ជា Async
if GROQ_API_KEY:
    client = AsyncGroq(api_key=GROQ_API_KEY)
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
2. **PRONUNCIATION:** 
   - For **English**, write the **SOUND** using Khmer letters.
   - For **Chinese**, write the **SOUND** using Khmer letters.

OUTPUT FORMAT (Use HTML Bold tags <b> </b>):
🇺🇸 <b>English:</b> [Text]
🗣️ <b>អានថា:</b> [English Sound in Khmer]
🇨🇳 <b>Chinese:</b> [Text] ([Pinyin])
🗣️ <b>អានថា:</b> [Chinese Sound in Khmer]
🇰🇭 <b>Khmer:</b> [Translation]
💡 <b>Grammar:</b> [Note]
"""

PROMPT_VOCAB = """
Generate 5 useful vocabulary words related to a random daily topic.
OUTPUT FORMAT PER WORD (No Markdown, just plain text or HTML):
[Number]. 🇺🇸 <b>[English Word]</b>
🗣️ [Write the ENGLISH SOUND using Khmer script]
🇨🇳 [Chinese Word] ([Pinyin])
🇰🇭 [Khmer Meaning]
"""

# ================= 3. HELPER FUNCTIONS =================
def load_users():
    if not os.path.exists(USERS_FILE): return set()
    try:
        with open(USERS_FILE, 'r') as f:
            data = json.load(f)
            return set(data)
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
        # 🔥 ប្រើ await ជាមួយ AsyncGroq
        response = await client.chat.completions.create(
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
        return "⚠️ មានបញ្ហាបច្ចេកទេសជាមួយ AI ។"

# 🔥 មុខងារ Text-to-Speech (ដំណើរការក្នុង Thread ដាច់ដោយឡែក)
def generate_tts_audio(text):
    """Function to generate audio blocking-safe"""
    tts = gTTS(text=text, lang='en')
    audio_data = BytesIO()
    tts.write_to_fp(audio_data)
    audio_data.seek(0)
    return audio_data

async def send_tts_audio(context, chat_id, text):
    try:
        # កែ Regex ដើម្បីចាប់យកអក្សរអង់គ្លេសបានត្រឹមត្រូវជាងមុន (ដក HTML tags ចេញ)
        clean_text = re.sub(r'<[^>]+>', '', text) # Remove HTML tags for regex checking
        match = re.search(r"🇺🇸\s*English:\s*(.+)", clean_text, re.IGNORECASE)
        
        english_text = ""
        if match:
            english_text = match.group(1).strip().split('\n')[0]
        
        # បើរកមិនឃើញតាម Format, សាករកតាម Vocab Format
        if not english_text:
            match_vocab = re.search(r"🇺🇸\s*([A-Za-z\s]+)", clean_text)
            if match_vocab:
                 english_text = match_vocab.group(1).strip()

        if not english_text or len(english_text) < 2: 
            return 

        # 🔥 Run gTTS in a separate thread to prevent blocking
        audio_data = await asyncio.to_thread(generate_tts_audio, english_text)
        
        await context.bot.send_voice(chat_id=chat_id, voice=audio_data)
            
    except Exception as e:
        logging.error(f"TTS Error: {e}")

# ================= 4. COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    current_users = load_users()
    
    # Alert Admin for new user
    if chat_id not in current_users:
        if ADMIN_ID and str(chat_id) != str(ADMIN_ID):
            full_name = user.full_name
            username = f"@{user.username}" if user.username else "❌ No Username"
            admin_alert = (
                f"🚨 <b>New User Joined!</b> 🚨\n\n"
                f"👤 <b>Name:</b> {full_name}\n"
                f"🆔 <b>Username:</b> {username}\n"
                f"🔢 <b>ID:</b> <code>{chat_id}</code>"
            )
            try:
                await context.bot.send_message(chat_id=int(ADMIN_ID), text=admin_alert, parse_mode=ParseMode.HTML)
            except Exception as e:
                logging.error(f"Failed to notify admin: {e}")
        
        save_user_to_file(chat_id)

    msg = (
        f"សួស្តី <b>{user.first_name}</b>! 👋\n"
        f"សូមស្វាគមន៍មកកាន់ <b>Bot ជំនួយការភាសា ៣ (ខ្មែរ-អង់គ្លេស-ចិន)</b> 🤖✨\n\n"
        f"ខ្ញុំអាចជួយអ្នកបកប្រែ កែវេយ្យាករណ៍ និងអានឱ្យស្តាប់បាន។\n\n"
        f"🛠 <b>របៀបប្រើប្រាស់៖</b>\n"
        f"1️⃣ <b>និយាយ (Voice):</b> ចុចរូប 🎙️ (Microphone) និយាយហើយផ្ញើមក។\n"
        f"2️⃣ <b>សរសេរ (Text):</b> វាយអក្សរខ្មែរ អង់គ្លេស ឬចិន មកខ្ញុំ។\n"
        f"3️⃣ <b>រៀនពាក្យ:</b> ចុចប៊ូតុង \"📚 រៀន Vocab\" នៅខាងក្រោម។\n\n"
        f"🆘 <b>ទាក់ទង Admin:</b>\n"
        f"• បើចង់ផ្ដល់យោបល់ វាយ៖ <code>/feedback [សាររបស់អ្នក]</code>\n"
        f"• បើ Bot គាំងប្រើមិនកើត សូមឆាតទៅ៖ {ADMIN_USERNAME}"
    )
    
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode=ParseMode.HTML)

async def vocab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user_to_file(update.effective_chat.id)
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    reply = await get_ai_response(PROMPT_VOCAB, "Generate vocabulary list.")
    
    # Convert markdown ** to HTML <b> just in case AI forgets
    reply = reply.replace("**", "") 
    
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML)

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ' '.join(context.args)
    user = update.effective_user
    if not msg:
        await update.message.reply_text("⚠️ សូមវាយ៖ <code>/feedback [សាររបស់អ្នក]</code>", parse_mode=ParseMode.HTML)
        return
    
    if ADMIN_ID:
        info = f"@{user.username}" if user.username else f"{user.first_name}"
        try:
            await context.bot.send_message(chat_id=int(ADMIN_ID), text=f"📩 <b>Feedback from {info}:</b>\n{msg}", parse_mode=ParseMode.HTML)
            await update.message.reply_text("✅ បានផ្ញើជូន Admin ហើយ!")
        except:
            await update.message.reply_text("❌ មិនអាចផ្ញើបាន។")
    else:
        await update.message.reply_text("❌ Admin ID មិនទាន់បានកំណត់។")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg}", parse_mode=ParseMode.HTML)
            count += 1
            await asyncio.sleep(0.05)
        except: 
            continue
    await update.message.reply_text(f"✅ បានផ្ញើជោគជ័យទៅកាន់ {count} នាក់។")

# ================= 5. MAIN HANDLERS =================

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

        # 🔥 Transcribe using AsyncGroq
        with open(file_name, "rb") as file:
            # Note: Groq Python library handles files a bit differently in async sometimes, 
            # but creating transcription usually needs to read the file.
            # Reading file content into memory for safe async handling:
            file_content = file.read()

        transcription = await client.audio.transcriptions.create(
            file=(file_name, file_content),
            model=GROQ_MODEL_AUDIO,
            response_format="text"
        )
        
        user_spoken_text = transcription
        await update.message.reply_text(f"🎤 <b>ឮថា:</b> <i>{user_spoken_text}</i>", parse_mode=ParseMode.HTML)
        
        # Translate
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        ai_reply = await get_ai_response(PROMPT_CONVERSATION, user_spoken_text)
        
        # Cleanup formatting for HTML
        ai_reply_html = ai_reply.replace("**", "") # AI might output markdown, strip it or let HTML handle it
        
        await update.message.reply_text(ai_reply_html, parse_mode=ParseMode.HTML)

        # TTS
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        await send_tts_audio(context, chat_id, ai_reply)

    except Exception as e:
        logging.error(f"Voice Error: {e}")
        await update.message.reply_text("⚠️ ស្តាប់មិនច្បាស់ ឬមានបញ្ហា។")
    
    finally:
        if os.path.exists(file_name):
            try:
                os.remove(file_name)
            except: pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "📚 រៀន Vocab": await vocab(update, context)
    elif text == "📩 Feedback": await update.message.reply_text("វាយ៖ <code>/feedback សារ</code>", parse_mode=ParseMode.HTML)
    elif text == "❓ ជំនួយ": await help_command(update, context)
    else:
        save_user_to_file(update.effective_chat.id)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        # Translate
        reply = await get_ai_response(PROMPT_CONVERSATION, text)
        
        # Cleanup formatting
        reply_html = reply.replace("**", "")

        await update.message.reply_text(reply_html, parse_mode=ParseMode.HTML)

        # TTS
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        await send_tts_audio(context, chat_id, reply)

# ================= 6. MAIN RUN =================
if __name__ == '__main__':
    keep_alive()
    
    if not TELEGRAM_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN is missing in .env file.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('vocab', vocab))
        app.add_handler(CommandHandler('feedback', feedback_command))
        app.add_handler(CommandHandler('broadcast', broadcast))
        app.add_handler(CommandHandler('help', help_command))
        app.add_handler(MessageHandler(filters.VOICE, handle_voice))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        print("✅ Bot is running...")
        app.run_polling(drop_pending_updates=True)
