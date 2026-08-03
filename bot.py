import logging
import uuid
import os
import gc
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# ========== فرمت‌ها ==========
def format_question(q, index, total):
    return f"**[{index+1}/{total}]** {q['question']}\n\n"

def format_result(is_correct, selected, correct, option_list):
    emoji = "✅" if is_correct else "❌"
    status = "پاسخ درست! 🎉" if is_correct else "پاسخ نادرست! 😞"
    text = f"{emoji} **{status}**\n\n"
    text += f"📌 **پاسخ شما:** {option_list[selected]}\n"
    text += f"✅ **پاسخ صحیح:** {option_list[correct]}\n"
    return text

def format_final_result(score, total, questions, answers):
    percent = round(score/total*100, 1)
    if percent >= 80:
        grade = "🌟 عالی! استاد شدی!"
    elif percent >= 60:
        grade = "💪 خوب! قابل قبوله!"
    elif percent >= 40:
        grade = "📚 نیاز به مطالعه بیشتر داری!"
    else:
        grade = "😅 باید بیشتر بخونی!"
    text = f"🏆 **نتیجه نهایی**\n\n"
    text += f"📊 **امتیاز:** {score} از {total}\n"
    text += f"📈 **درصد:** {percent}%\n"
    text += f"💬 **{grade}**\n\n"
    text += "📝 **پاسخنامه (۱۰ سوال اول):**\n"
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
        "📤 فایل PDF، Word یا txt بفرست\n"
        "📝 یا /newquiz بساز\n"
        "🎯 /quiz شروع\n"
        f"⏱️ هر سوال {TIMER_SECONDS} ثانیه\n"
        "🔗 /share لینک اشتراک\n"
        "📊 /stats آمار"
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
        db.save_questions(quiz_id, questions[i:i+100])
    del quiz_builders[user_id]
    await update.message.reply_text(f"✅ {len(questions)} سوال ذخیره شد! /quiz")

async def cancel_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in quiz_builders:
        del quiz_builders[user_id]
        await update.message.reply_text("❌ لغو شد!")
    else:
        await update.message.reply_text("❌ در حال ساخت نیستی!")

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

async def share_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.cursor.execute("SELECT quiz_id, score, total FROM user_scores WHERE user_id=? ORDER BY timestamp DESC LIMIT 1", (user_id,))
    row = db.cursor.fetchone()
    if not row:
        await update.message.reply_text("❌ هنوز کوئیز کامل نکردی!")
        return
    share_link = f"https://t.me/{context.bot.username}?start=share_{row[0]}"
    await update.message.reply_text(f"🔗 لینک اشتراک: {share_link}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.cursor.execute("SELECT COUNT(*) FROM user_scores WHERE user_id=?", (user_id,))
    total = db.cursor.fetchone()[0]
    db.cursor.execute("SELECT AVG(score*1.0/total*100) FROM user_scores WHERE user_id=?", (user_id,))
    avg = db.cursor.fetchone()[0] or 0
    db.cursor.execute("SELECT score, total FROM user_scores WHERE user_id=? ORDER BY timestamp DESC LIMIT 1", (user_id,))
    last = db.cursor.fetchone()
    text = f"📊 **آمار شما**\n📝 تعداد: {total}\n📈 میانگین: {round(avg,1)}%"
    if last:
        text += f"\n🔴 آخرین: {last[0]} از {last[1]} ({round(last[0]/last[1]*100,1)}%)"
    await update.message.reply_text(text)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    doc = update.message.document
    if doc.mime_type not in ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']:
        await update.message.reply_text("❌ فقط PDF، Word یا txt!")
        return
    await update.message.reply_text("📄 در حال پردازش...")
    file = await doc.get_file()
    file_path = f"temp_{user_id}.{doc.file_name.split('.')[-1]}"
    await file.download_to_drive(file_path)
    text = FileProcessor.extract_text(file_path)
    os.remove(file_path)
    gc.collect()
    if len(text.strip()) < 50:
        await update.message.reply_text("⚠️ متن کافی نیست!")
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

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
    db.save_session(user_id, quiz_id, 0, [])
    await show_question(update, context, user_id, quiz_id, 0)

async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, quiz_id, index):
    questions = db.get_questions(quiz_id)
    if index >= len(questions):
        await finish_quiz(update, context, user_id, quiz_id)
        return
    q = questions[index]
    keyboard = []
    for i, opt in enumerate(q['options']):
        keyboard.append([InlineKeyboardButton(f"{['الف','ب','ج','د'][i]}) {opt}", callback_data=f"ans_{quiz_id}_{index}_{i}")])
    if index > 0:
        keyboard.append([InlineKeyboardButton("⬅️ قبلی", callback_data=f"nav_{quiz_id}_{index-1}")])
    if index < len(questions)-1:
        keyboard.append([InlineKeyboardButton("بعدی ➡️", callback_data=f"nav_{quiz_id}_{index+1}")])
    keyboard.append([InlineKeyboardButton("🏁 پایان", callback_data=f"finish_{quiz_id}")])
    text = format_question(q, index, len(questions)) + f"⏱️ {TIMER_SECONDS}s"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    if user_id in active_timers:
        active_timers[user_id].cancel()
    active_timers[user_id] = asyncio.create_task(start_timer(update, context, user_id, quiz_id, index))

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

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data.split('_')
    if data[0] == 'ready':
        await ready_quiz(update, context)
        return
    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]

    if data[0] == 'nav':
        quiz_id = data[1]
        new_index = int(data[2])
        session = db.get_session(user_id)
        if session:
            await db.save_session(user_id, quiz_id, new_index, session['answers'])
        await show_question(update, context, user_id, quiz_id, new_index)
        return

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
    result_text = format_result(is_correct, selected, correct, q['options'])
    total_answers = len([a for a in answers if a != -1]) or 1
    percentages = []
    for i in range(len(q['options'])):
        percentages.append(round(sum(1 for a in answers if a == i) / total_answers * 100))
    result_text += "\n📊 درصدها:\n"
    for i, opt in enumerate(q['options']):
        result_text += f"{['الف','ب','ج','د'][i]}) {opt}: {percentages[i] if i < len(percentages) else 0}%\n"
    next_index = q_index + 1
    keyboard = []
    if next_index < len(questions):
        keyboard.append([InlineKeyboardButton("➡️ سوال بعدی", callback_data=f"next_{quiz_id}_{next_index}")])
    keyboard.append([InlineKeyboardButton("🏁 پایان", callback_data=f"finish_{quiz_id}")])
    await query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    await show_question(update, context, update.effective_user.id, data[1], int(data[2]))

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
    result_text = format_final_result(score, len(questions), questions, answers)
    if update.callback_query:
        await update.callback_query.edit_message_text(result_text)
    else:
        await update.message.reply_text(result_text)
    db.cursor.execute("DELETE FROM active_sessions WHERE user_id=?", (user_id,))
    db.conn.commit()

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
    app.add_handler(CommandHandler("share", share_quiz))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_builder))
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^(ans_|ready_|nav_|finish_)"))
    app.add_handler(CallbackQueryHandler(next_question, pattern="^next_"))

    logger.info("🤖 ربات هوشمند روشن شد (حالت Webhook)")

    PORT = int(os.environ.get('PORT', 8443))
    RAILWAY_DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    if not RAILWAY_DOMAIN:
        RAILWAY_DOMAIN = "YOUR_RAILWAY_APP_NAME.railway.app"
        logger.warning("RAILWAY_PUBLIC_DOMAIN پیدا نشد، از مقدار پیش‌فرض استفاده می‌شود.")

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
