import logging
import uuid
import os
import gc
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from database import Database
from pdf_processor import FileProcessor

try:
    from PIL import Image
except ImportError:
    Image = None

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
        "📤 حداکثر ۵ مگابایت فایل PDF بفرست\n"
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

# ========== هندل کردن فایل‌ها و عکس‌ها ==========
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    doc = update.message.document
    
    # ===== چک کردن حجم فایل (محافظت در برابر فایل‌های بزرگ) =====
    if doc.file_size > 5 * 1024 * 1024:  # 5 مگابایت
        await update.message.reply_text(
            "⚠️ **حجم فایل خیلی زیاد است!**\n\n"
            "سرور رایگان فقط می‌تواند فایل‌های زیر ۵ مگابایت را پردازش کند.\n"
            "لطفاً فایل را با سایت‌هایی مثل **iLovePDF** یا **SmallPDF** فشرده کنید و دوباره بفرستید."
        )
        return

    if doc.mime_type not in ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']:
        await update.message.reply_text("❌ فقط PDF، Word یا txt!")
        return
        
    await update.message.reply_text("📄 در حال پردازش فایل... (برای فایل‌های اسکن‌شده کمی صبر کنید)")
    file = await doc.get_file()
    file_path = f"temp_{user_id}.{doc.file_name.split('.')[-1]}"
    await file.download_to_drive(file_path)
    text = FileProcessor.extract_text(file_path)
    os.remove(file_path)
    gc.collect()
    if len(text.strip()) < 50:
        await update.message.reply_text("⚠️ متنی در فایل پیدا نشد! (فایل اسکن‌شده است یا متن کافی ندارد).")
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
    await update.message.reply_text("📸 عکس دریافت شد، در حال استخراج متن با هوش مصنوعی...")
    
    if not Image:
        await update.message.reply_text("❌ کتابخانه پردازش عکس نصب نیست! (Pillow)")
        return
        
    try:
        import pytesseract
    except ImportError:
        await update.message.reply_text("❌ OCR نصب نیست!")
        return

    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_path = f"temp_photo_{user_id}.jpg"
    await file.download_to_drive(file_path)

    try:
        text = FileProcessor.extract_text_from_image_ai(file_path)
        os.remove(file_path)
        
        if len(text.strip()) < 50:
            await update.message.reply_text("⚠️ متنی در این عکس پیدا نشد (خیلی تار یا کمرنگ است).")
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

# ========== حالت تکی کوئیز ==========
async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
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
        keyboard = [[InlineKeyboardButton("✅ آماده شروع", callback_data=f"group_ready_{quiz_id}")]]
        await update.message.reply_text(
            f"🎯 کوئیز گروهی شروع میشه!\n📝 {len(db.get_questions(quiz_id))} سوال\n⏱️ {TIMER_SECONDS}s هر سوال\n\n👇 اعضای گروه روی دکمه زیر بزنند تا شروع شود!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

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
    chat_id = update.effective_chat.id
    data = query.data.split('_')
    
    # حالت گروهی
    if data[0] == 'group_ready':
        await group_ready_quiz(update, context)
        return
    elif data[0] == 'g_ans':
        quiz_id = data[1]
        q_index = int(data[2])
        selected = int(data[3])
        success = await db.save_group_answer(chat_id, user_id, q_index, selected)
        if success:
            await query.edit_message_text("✅ پاسخ شما ثبت شد!", reply_markup=None)
        else:
            await query.edit_message_text("⚠️ شما قبلاً به این سوال پاسخ داده‌اید!", reply_markup=None)
        return
    elif data[0] == 'g_finish':
        await finish_group_quiz(update, context, chat_id, data[1])
        return
    
    # حالت تکی
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

# حالت گروهی کوئیز
async def group_ready_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    quiz_id = query.data.split('_')[2]
    session = db.get_group_session(chat_id)
    if session:
        await show_question_group(update, context, chat_id, quiz_id, 0)

async def show_question_group(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id, quiz_id, index):
    questions = db.get_questions(quiz_id)
    if index >= len(questions):
        await finish_group_quiz(update, context, chat_id, quiz_id)
        return
    q = questions[index]
    keyboard = []
    for i, opt in enumerate(q['options']):
        keyboard.append([InlineKeyboardButton(f"{['الف','ب','ج','د'][i]}) {opt}", callback_data=f"g_ans_{quiz_id}_{index}_{i}")])
    keyboard.append([InlineKeyboardButton("⏹️ پایان کوئیز", callback_data=f"g_finish_{quiz_id}")])
    
    text = f"**[{index+1}/{len(questions)}]** {q['question']}\n\n⏱️ {TIMER_SECONDS}s"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

    if chat_id in active_timers:
        active_timers[chat_id].cancel()
    active_timers[chat_id] = asyncio.create_task(start_group_timer(update, context, chat_id, quiz_id, index))

async def start_group_timer(update, context, chat_id, quiz_id, index):
    try:
        await asyncio.sleep(TIMER_SECONDS - WARNING_SECONDS)
        session = db.get_group_session(chat_id)
        if session and session['quiz_id'] == quiz_id:
            await context.bot.send_message(chat_id, f"⚠️ {WARNING_SECONDS}s مونده!")
        await asyncio.sleep(WARNING_SECONDS)
        session = db.get_group_session(chat_id)
        if session and session['quiz_id'] == quiz_id:
            next_index = index + 1
            questions = db.get_questions(quiz_id)
            if next_index >= len(questions):
                await finish_group_quiz(update, context, chat_id, quiz_id)
            else:
                await db.save_group_session(chat_id, quiz_id, next_index)
                await context.bot.send_message(chat_id, f"⏰ زمان سوال {index+1} تموم شد!")
                await show_question_group(update, context, chat_id, quiz_id, next_index)
    except asyncio.CancelledError:
        pass
    finally:
        if chat_id in active_timers:
            del active_timers[chat_id]

async def finish_group_quiz(update, context, chat_id, quiz_id):
    if chat_id in active_timers:
        active_timers[chat_id].cancel()
        del active_timers[chat_id]
        
    questions = db.get_questions(quiz_id)
    all_answers = db.get_all_group_answers(chat_id, len(questions))
    
    result_text = f"🏆 **نتیجه نهایی کوئیز گروهی**\n\n"
    user_scores = {}
    
    for user_id, ans in all_answers.items():
        score = 0
        for i, q in enumerate(questions):
            if i in ans and ans[i] == q['correct_answer']:
                score += 1
        user_scores[user_id] = score
        
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            name = member.user.first_name
        except:
            name = f"User {user_id}"
        
        percent = round(score/len(questions)*100, 1)
        result_text += f"👤 **{name}**: {score} از {len(questions)} ({percent}%)\n"
    
    await context.bot.send_message(chat_id, result_text)
    db.cursor.execute("DELETE FROM group_sessions WHERE chat_id=?", (chat_id,))
    db.conn.commit()

# بخش اصلی
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
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_builder))
    
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^(ans_|ready_|nav_|finish_|group_ready|g_ans|g_finish)"))
    app.add_handler(CallbackQueryHandler(next_question, pattern="^next_"))

    logger.info("🤖 ربات هوشمند روشن شد (حالت Webhook)")

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
