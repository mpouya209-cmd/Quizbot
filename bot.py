import logging
import uuid
import os
import gc
import asyncio
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from database import Database
from pdf_processor import FileProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()

# ========== تنظیمات ==========
TIMER_SECONDS = 30
WARNING_SECONDS = 10
active_timers = {}
quiz_builders = {}
quiz_ready = {}

# ========== فرمت نتیجه ==========
def format_result_card(score, total, questions, answers):
    percent = round(score/total*100, 1)
    mistakes = total - score
    
    if percent >= 80:
        grade = "🌟 عالی! استاد شدی!"
    elif percent >= 60:
        grade = "💪 خوب! قابل قبول!"
    elif percent >= 40:
        grade = "📚 نیاز به مطالعه بیشتر داری!"
    else:
        grade = "😅 باید بیشتر بخونی!"

    text = (
        "📊 **نتیجه آزمون**\n\n"
        f"✅ درست: {score}\n"
        f"❌ اشتباه: {mistakes}\n"
        f"⏱️ زمان: {TIMER_SECONDS} ثانیه\n\n"
        f"📈 **رتبه شما:** {score} از {total} ({percent}%)\n"
        f"🏅 **{grade}**\n\n"
        "📝 **پاسخنامه (۱۰ سوال اول):**\n"
    )

    for i in range(min(10, total)):
        q = questions[i]
        user_ans = answers[i] if i < len(answers) and answers[i] != -1 else "نزده"
        correct = q['correct_answer']
        status = "✅" if user_ans == correct else "❌"
        text += f"{status} سوال {i+1}: {q['options'][correct]}\n"

    if total > 10:
        text += f"\n... و {total-10} سوال دیگر"
    
    return text

# ========== دستورات ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **به ربات کوئیز ساز خوش آمدید!**\n\n"
        "📤 فایل PDF، Word، txt یا عکس بفرست\n"
        "📝 یا /newquiz بساز\n"
        "🎯 /quiz شروع\n"
        f"⏱️ هر سوال {TIMER_SECONDS} ثانیه\n"
    )

async def new_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    quiz_id = str(uuid.uuid4())[:8]
    quiz_builders[user_id] = {'quiz_id': quiz_id, 'questions': [], 'step': 'question'}
    await update.message.reply_text("📝 سوال اول رو بفرست (لغو: /cancel)")

async def done_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in quiz_builders:
        await update.message.reply_text("❌ در حال ساخت کوئیز نیستی!")
        return
    builder = quiz_builders[user_id]
    questions = builder['questions']
    if len(questions) < 1:
        await update.message.reply_text("❌ حداقل ۱ سوال نیازه!")
        return
    quiz_id = builder['quiz_id']
    for i in range(0, len(questions), 100):
        await db.save_questions(quiz_id, questions[i:i+100])
    del quiz_builders[user_id]
    await update.message.reply_text(f"✅ {len(questions)} سوال ذخیره شد! /quiz")

async def cancel_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in quiz_builders:
        del quiz_builders[user_id]
        await update.message.reply_text("❌ لغو شد!")
    else:
        await update.message.reply_text("❌ در حال ساخت نیستی!")

# ========== هندلر یکباره متن ==========
async def handle_text_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if not re.search(r'\d+[\.\-\)]\s', text) and not re.search(r'الف\)|ب\)|ج\)|د\)', text):
        return

    await update.message.reply_text("📝 در حال پردازش متن ارسالی به عنوان سوالات کوئیز...")
    questions = FileProcessor.parse_questions_from_text(text)

    if not questions:
        await update.message.reply_text("❌ سوالی در متن پیدا نشد! فرمت سوالات (مثلاً 1- سوال, الف) گزینه) را رعایت کنید.")
        return

    if len(questions) > 1100:
        questions = questions[:1100]

    quiz_id = str(uuid.uuid4())[:8]
    for i in range(0, len(questions), 100):
        await db.save_questions(quiz_id, questions[i:i+100])

    await update.message.reply_text(f"✅ {len(questions)} سوال از متن استخراج شد! /quiz")

async def handle_quiz_builder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in quiz_builders:
        return
    builder = quiz_builders[user_id]
    text = update.message.text
    if builder['step'] == 'question':
        builder['current_question'] = text
        builder['step'] = 'options'
        await update.message.reply_text("✅ ۴ گزینه رو هر خط یکی بفرست:")
    elif builder['step'] == 'options':
        options = [opt.strip() for opt in text.split('\n') if opt.strip()]
        if len(options) < 2:
            await update.message.reply_text("❌ حداقل ۲ گزینه! دوباره بفرست:")
            return
        builder['questions'].append({
            'question': builder['current_question'][:500],
            'options': options[:4],
            'correct_answer': 0
        })
        builder['step'] = 'question'
        await update.message.reply_text(f"✅ سوال {len(builder['questions'])} ذخیره شد! (بعدی یا /done)")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    doc = update.message.document
    if doc.mime_type not in ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']:
        await update.message.reply_text("❌ فقط PDF، Word یا txt!")
        return
    await update.message.reply_text("📄 در حال پردازش فایل...")
    file = await doc.get_file()
    file_path = f"temp_{user_id}.{doc.file_name.split('.')[-1]}"
    await file.download_to_drive(file_path)
    text = FileProcessor.extract_text(file_path)
    os.remove(file_path)
    gc.collect()
    if len(text.strip()) < 50:
        await update.message.reply_text("⚠️ متن کافی در فایل پیدا نشد!")
        return
    questions = FileProcessor.parse_questions_from_text(text)
    if not questions:
        await update.message.reply_text("❌ سوالی پیدا نشد!")
        return
    if len(questions) > 1100:
        questions = questions[:1100]
    quiz_id = str(uuid.uuid4())[:8]
    for i in range(0, len(questions), 100):
        await db.save_questions(quiz_id, questions[i:i+100])
    await update.message.reply_text(f"✅ {len(questions)} سوال استخراج شد! /quiz")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("📸 عکس دریافت شد، در حال استخراج متن...")
    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_path = f"temp_photo_{user_id}.jpg"
    await file.download_to_drive(file_path)
    try:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(file_path), lang='fas+eng')
        os.remove(file_path)
        if len(text.strip()) < 50:
            await update.message.reply_text("⚠️ متنی در این عکس پیدا نشد.")
            return
        questions = FileProcessor.parse_questions_from_text(text)
        if not questions:
            await update.message.reply_text("❌ سوالی پیدا نشد!")
            return
        quiz_id = str(uuid.uuid4())[:8]
        for i in range(0, len(questions), 100):
            await db.save_questions(quiz_id, questions[i:i+100])
        await update.message.reply_text(f"✅ {len(questions)} سوال از عکس استخراج شد! /quiz")
    except Exception as e:
        await update.message.reply_text(f"خطا در پردازش عکس: {str(e)}")

# ========== حالت گروهی با نظرسنجی ==========
async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # اگر در گروه هستیم
    if update.effective_chat.type in ['group', 'supergroup']:
        session = db.get_group_session(chat_id)
        if session:
            await update.message.reply_text("⏳ یک کوئیز در این گروه در حال اجراست!")
            return

        db.cursor.execute("SELECT DISTINCT quiz_id FROM questions ORDER BY id DESC LIMIT 1")
        row = db.cursor.fetchone()
        if not row:
            await update.message.reply_text("📤 اول فایل بفرست یا /newquiz تو گروه بساز!")
            return

        quiz_id = row[0]
        await db.save_group_session(chat_id, quiz_id, 0)
        questions = db.get_questions(quiz_id)
        
        keyboard = [[InlineKeyboardButton("✅ آماده شروع", callback_data=f"group_ready_{quiz_id}")]]
        await update.message.reply_text(
            f"🎯 کوئیز گروهی شروع میشه!\n📝 {len(questions)} سوال\n⏱️ {TIMER_SECONDS}s هر سوال\n\n👇 اعضای گروه روی دکمه زیر بزنند تا شروع شود!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # حالت تکی
    session = db.get_session(user_id)
    if session:
        await update.message.reply_text("⏳ ادامه قبلی...")
        await show_question(update, context, user_id, session['quiz_id'], session['current_question'])
        return

    db.cursor.execute("SELECT DISTINCT quiz_id FROM questions ORDER BY id DESC LIMIT 1")
    row = db.cursor.fetchone()
    if not row:
        await update.message.reply_text("📤 اول فایل بفرست یا /newquiz")
        return

    quiz_id = row[0]
    questions = db.get_questions(quiz_id)
    if not questions:
        await update.message.reply_text("❌ سوالی نیست!")
        return

    keyboard = [[InlineKeyboardButton("✅ حاضر", callback_data=f"ready_{quiz_id}")]]
    await update.message.reply_text(
        f"🎯 آماده‌ای؟\n📝 {len(questions)} سوال\n⏱️ {TIMER_SECONDS}s هر سوال",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ready_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    quiz_id = query.data.split('_')[1]
    quiz_ready[user_id] = True
    await db.save_session(user_id, quiz_id, 0, [])
    await show_question(update, context, user_id, quiz_id, 0)

# ========== نمایش سوالات ==========
async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, quiz_id, index):
    questions = db.get_questions(quiz_id)
    if index >= len(questions):
        await finish_quiz(update, context, user_id, quiz_id)
        return

    q = questions[index]
    
    # دکمه‌های گزینه‌ها (برای حالت تکی)
    keyboard = []
    for i, opt in enumerate(q['options']):
        keyboard.append([InlineKeyboardButton(f"{['الف','ب','ج','د'][i]}) {opt}", callback_data=f"ans_{quiz_id}_{index}_{i}")])
    
    # فقط دکمه پایان، بدون قبلی و بعدی
    keyboard.append([InlineKeyboardButton("🏁 پایان", callback_data=f"finish_{quiz_id}")])

    text = f"📝 **سوال {index+1} از {len(questions)}**\n\n{q['question']}\n\n⏱️ {TIMER_SECONDS}s"

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    if user_id in active_timers:
        active_timers[user_id].cancel()
    active_timers[user_id] = asyncio.create_task(start_timer(update, context, user_id, quiz_id, index))

# ========== نمایش سوالات گروهی ==========
async def show_question_group(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id, quiz_id, index):
    questions = db.get_questions(quiz_id)
    if index >= len(questions):
        await finish_group_quiz(update, context, chat_id, quiz_id)
        return

    q = questions[index]
    options = q['options']
    
    # ارسال نظرسنجی (Poll)
    await context.bot.send_poll(
        chat_id=chat_id,
        question=f"**[{index+1}/{len(questions)}]** {q['question']}",
        options=options[:4],
        is_anonymous=False,
        type=Poll.QUIZ,
        correct_option_id=q['correct_answer'],
        open_period=TIMER_SECONDS
    )
    
    # ارسال پیام زمان‌دار در زیر نظرسنجی
    await context.bot.send_message(
        chat_id,
        f"⏱️ {TIMER_SECONDS} ثانیه برای پاسخگویی..."
    )

    # تایمر گروهی
    if chat_id in active_timers:
        active_timers[chat_id].cancel()
    active_timers[chat_id] = asyncio.create_task(start_group_timer(update, context, chat_id, quiz_id, index))

async def start_timer(update, context, user_id, quiz_id, index):
    try:
        await asyncio.sleep(TIMER_SECONDS - WARNING_SECONDS)
        session = db.get_session(user_id)
        if session and session['quiz_id'] == quiz_id:
            answers = session['answers']
            if len(answers) <= index or answers[index] == -1:
                await update.message.reply_text(f"⚠️ {WARNING_SECONDS}s مونده!")
        await asyncio.sleep(WARNING_SECONDS)
        session = db.get_session(user_id)
        if session and session['quiz_id'] == quiz_id:
            answers = session['answers']
            if len(answers) <= index or answers[index] == -1:
                next_index = index + 1
                questions = db.get_questions(quiz_id)
                if next_index >= len(questions):
                    await finish_quiz(update, context, user_id, quiz_id)
                else:
                    if len(answers) <= index:
                        answers.append(-1)
                    else:
                        answers[index] = -1
                    await db.save_session(user_id, quiz_id, next_index, answers)
                    await update.message.reply_text(f"⏰ زمان سوال {index+1} تموم شد!")
                    await show_question(update, context, user_id, quiz_id, next_index)
    except asyncio.CancelledError:
        pass
    finally:
        if user_id in active_timers:
            del active_timers[user_id]

async def start_group_timer(update, context, chat_id, quiz_id, index):
    try:
        # صبر می‌کنیم تا زمان نظرسنجی تموم بشه
        await asyncio.sleep(TIMER_SECONDS + 1)
        session = db.get_group_session(chat_id)
        if session and session['quiz_id'] == quiz_id:
            next_index = index + 1
            questions = db.get_questions(quiz_id)
            if next_index >= len(questions):
                await finish_group_quiz(update, context, chat_id, quiz_id)
            else:
                await db.save_group_session(chat_id, quiz_id, next_index)
                # ارسال سوال بعدی به‌صورت یک پیام جدید در پایین‌تر
                await show_question_group(update, context, chat_id, quiz_id, next_index)
    except asyncio.CancelledError:
        pass
    finally:
        if chat_id in active_timers:
            del active_timers[chat_id]

# ========== هندلر پاسخ‌ها ==========
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    data = query.data.split('_')

    if data[0] == 'group_ready':
        await group_ready_quiz(update, context)
        return

    if data[0] == 'ready':
        await ready_quiz(update, context)
        return

    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]

    if data[0] == 'finish':
        await finish_quiz(update, context, user_id, data[1])
        return

    quiz_id = data[1]
    q_index = int(data[2])
    selected = int(data[3])
    session = db.get_session(user_id)
    if not session:
        await query.edit_message_text("⏳ جلسه تموم شد!")
        return

    questions = db.get_questions(quiz_id)
    if q_index >= len(questions):
        await finish_quiz(update, context, user_id, quiz_id)
        return

    q = questions[q_index]
    correct = q['correct_answer']
    is_correct = (selected == correct)
    answers = session['answers']
    while len(answers) <= q_index:
        answers.append(-1)
    answers[q_index] = selected
    await db.save_session(user_id, quiz_id, q_index + 1, answers)

    # نمایش نتیجه و رفتن مستقیم به سوال بعدی
    result_text = f"✅ پاسخ صحیح: {q['options'][correct]}\n" if is_correct else f"❌ پاسخ شما: {q['options'][selected]}\n✅ پاسخ صحیح: {q['options'][correct]}"
    
    next_index = q_index + 1
    if next_index < len(questions):
        # اگر سوال بعدی وجود دارد، مستقیماً برو
        await query.edit_message_text(result_text)
        await show_question(update, context, user_id, quiz_id, next_index)
    else:
        # اگر سوال آخر بود، برو به پایان
        await query.edit_message_text(result_text)
        await finish_quiz(update, context, user_id, quiz_id)

async def group_ready_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    quiz_id = query.data.split('_')[2]
    session = db.get_group_session(chat_id)
    if session:
        await show_question_group(update, context, chat_id, quiz_id, 0)

async def finish_quiz(update, context, user_id, quiz_id):
    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]
    questions = db.get_questions(quiz_id)
    session = db.get_session(user_id)
    if not session:
        return
    answers = session['answers']
    score = sum(1 for i, q in enumerate(questions) if i < len(answers) and answers[i] == q['correct_answer'])
    await db.save_score(user_id, quiz_id, score, len(questions), answers)

    result_text = format_result_card(score, len(questions), questions, answers)
    keyboard = [
        [InlineKeyboardButton("🔄 دوباره تلاش کنید", callback_data=f"retry_{quiz_id}")],
        [InlineKeyboardButton("🔗 به اشتراک گذاشتن آزمون", callback_data=f"share_{quiz_id}")],
        [InlineKeyboardButton("⏸️ توقف", callback_data=f"stop_{quiz_id}")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    db.cursor.execute("DELETE FROM active_sessions WHERE user_id=?", (user_id,))
    db.conn.commit()

async def finish_group_quiz(update, context, chat_id, quiz_id):
    if chat_id in active_timers:
        active_timers[chat_id].cancel()
        del active_timers[chat_id]

    questions = db.get_questions(quiz_id)
    await context.bot.send_message(
        chat_id,
        f"🏆 **کوئیز گروهی به پایان رسید!**\n\n"
        f"📝 {len(questions)} سوال"
    )
    
    db.cursor.execute("DELETE FROM group_sessions WHERE chat_id=?", (chat_id,))
    db.conn.commit()

# ========== هندلرهای دکمه‌ها ==========
async def handle_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    quiz_id = query.data.split('_')[1]
    await db.save_session(user_id, quiz_id, 0, [])
    await query.edit_message_text("🔄 شروع مجدد آزمون...")
    await show_question(update, context, user_id, quiz_id, 0)

async def handle_share_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    quiz_id = query.data.split('_')[1]
    share_link = f"https://t.me/{context.bot.username}?start=share_{quiz_id}"
    await query.edit_message_text(
        f"🔗 **لینک اشتراک آزمون**\n\n"
        f"برای شرکت دیگران در این آزمون، لینک زیر را بفرستید:\n"
        f"`{share_link}`"
    )

async def handle_stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]
    db.cursor.execute("DELETE FROM active_sessions WHERE user_id=?", (user_id,))
    db.conn.commit()
    await query.edit_message_text("⏸️ آزمون متوقف شد.")

# ========== زمان‌بند خواب ==========
async def sleep_scheduler(context: ContextTypes.DEFAULT_TYPE):
    """
    این تابع هر دقیقه یکبار اجرا می‌شود و ساعت را چک می‌کند.
    اگر ساعت بین ۲۴:۰۰ تا ۰۸:۰۰ به وقت ایران باشد، وب‌هوک را قطع می‌کند.
    در غیر این صورت، وب‌هوک را وصل می‌کند.
    """
    TOKEN = context.bot.token
    
    # محاسبه دقیق ساعت ایران (UTC + 3:30)
    now_utc = datetime.utcnow()
    total_minutes_utc = now_utc.hour * 60 + now_utc.minute
    total_minutes_iran = total_minutes_utc + 210
    hour_iran = (total_minutes_iran // 60) % 24
    minute_iran = total_minutes_iran % 60
    
    # بازه خواب: از ۰۰:۰۰ تا ۰۸:۰۰ به وقت ایران
    is_sleep_time = (hour_iran >= 0 and hour_iran < 8)
    
    try:
        webhook_info = await context.bot.get_webhook_info()
        current_url = webhook_info.url
        
        if is_sleep_time:
            if current_url:
                logger.info(f"😴 ساعت خواب ({hour_iran:02d}:{minute_iran:02d}) - قطع کردن وب‌هوک...")
                await context.bot.delete_webhook()
        else:
            if not current_url:
                logger.info(f"☀️ ساعت بیداری ({hour_iran:02d}:{minute_iran:02d}) - وصل کردن وب‌هوک...")
                PORT = int(os.environ.get('PORT', 8443))
                RAILWAY_DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
                if not RAILWAY_DOMAIN:
                    PUBLIC_URL = "https://web-production-8e010.up.railway.app"
                else:
                    PUBLIC_URL = f"https://{RAILWAY_DOMAIN}"
                WEBHOOK_URL = f"{PUBLIC_URL}/{TOKEN}"
                await context.bot.set_webhook(url=WEBHOOK_URL)
    except Exception as e:
        logger.error(f"خطا در مدیریت خواب ربات: {e}")

# ========== بخش اصلی ==========
def main():
    TOKEN = os.environ.get('TOKEN')
    if not TOKEN:
        print("Error: TOKEN is not set in environment variables.")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("newquiz", new_quiz))
    app.add_handler(CommandHandler("done", done_quiz))
    app.add_handler(CommandHandler("cancel", cancel_quiz))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_quiz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_builder))

    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^(ans_|ready_|finish_|group_ready)"))
    app.add_handler(CallbackQueryHandler(handle_retry, pattern="^retry_"))
    app.add_handler(CallbackQueryHandler(handle_share_quiz, pattern="^share_"))
    app.add_handler(CallbackQueryHandler(handle_stop_quiz, pattern="^stop_"))

    logger.info("🤖 ربات با زمان‌بند خواب روشن شد!")

    # راه‌اندازی زمان‌بند خواب (هر ۶۰ ثانیه)
    job_queue = app.job_queue
    job_queue.run_repeating(sleep_scheduler, interval=60, first=10)

    PORT = int(os.environ.get('PORT', 8443))
    RAILWAY_DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN')

    if not RAILWAY_DOMAIN:
        PUBLIC_URL = "https://web-production-8e010.up.railway.app"
    else:
        PUBLIC_URL = f"https://{RAILWAY_DOMAIN}"

    WEBHOOK_URL = f"{PUBLIC_URL}/{TOKEN}"

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
