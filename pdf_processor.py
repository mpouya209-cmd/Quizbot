import re
import os
import json
from openai import OpenAI

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

try:
    import PyPDF2
except ImportError: PyPDF2 = None
try:
    import docx2txt
except ImportError: docx2txt = None


class FileProcessor:
    @staticmethod
    def extract_text_from_docx(file_path):
        if docx2txt:
            try:
                return docx2txt.process(file_path)
            except:
                return ""
        return ""

    @staticmethod
    def extract_text_from_pdf(file_path):
        text = ""
        if PyPDF2:
            try:
                with open(file_path, 'rb') as file:
                    reader = PyPDF2.PdfReader(file)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                return text
            except:
                pass
        return ""

    @staticmethod
    def extract_text(file_path):
        if file_path.endswith('.docx'):
            return FileProcessor.extract_text_from_docx(file_path)
        elif file_path.endswith('.pdf'):
            return FileProcessor.extract_text_from_pdf(file_path)
        else:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except:
                return ""

    @staticmethod
    def parse_questions_from_text(text):
        questions = []
        
        # ===== روش 1: جداسازی با الگوی Regex (سریع و بدون هزینه) =====
        # تمام متن را بر اساس الگوی "عدد) " یا "عدد- " تقسیم می‌کنیم
        raw_questions = re.split(r'(\d+[\.\-\)]\s*)', text)
        
        current_question = ""
        current_options = []
        
        for i, part in enumerate(raw_questions):
            # اگر بخش، یک شماره سوال بود (مثل "۱- ")
            if re.match(r'^\d+[\.\-\)]\s*$', part):
                # اگر سوال قبلی کامل بود و گزینه داشت، ذخیره‌اش کن
                if current_question and len(current_options) >= 2:
                    questions.append({
                        'question': current_question[:500],
                        'options': current_options[:4],
                        'correct_answer': 0
                    })
                # شروع یک سوال جدید
                current_question = ""
                current_options = []
            else:
                # این بخش، متن سوال یا گزینه‌هاست
                text_part = part.strip()
                if not text_part:
                    continue
                
                # اگر خط شامل حروف الف، ب، ج، د به‌همراه ) یا . بود، گزینه است
                if re.search(r'[الف-ی]\.|الف\)|ب\)|ج\)|د\)', text_part):
                    # گزینه‌ها را با جداسازی بر اساس حروف الفبا جدا کن
                    options_raw = re.split(r'([الف-ی][\.\)])', text_part)
                    opt_text = ""
                    for opt in options_raw:
                        if re.match(r'[الف-ی][\.\)]', opt):
                            # شروع یک گزینه جدید
                            if opt_text:
                                current_options.append(opt_text.strip())
                            opt_text = ""
                        else:
                            opt_text += opt.strip() + " "
                    if opt_text:
                        current_options.append(opt_text.strip())
                else:
                    # اگر گزینه نبود، به متن سوال اضافه کن
                    current_question += " " + text_part
        
        # ذخیره آخرین سوال
        if current_question and len(current_options) >= 2:
            questions.append({
                'question': current_question[:500],
                'options': current_options[:4],
                'correct_answer': 0
            })
        
        # ===== روش 2: اگر Regex موفق نشد، هوش مصنوعی Groq را صدا کن =====
        if not questions and GROQ_API_KEY:
            try:
                client = OpenAI(
                    api_key=GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1"
                )
                prompt = f"""
                متن زیر یک آزمون است. لطفاً سوالات و گزینه‌ها را به فرمت JSON استخراج کن.
                خروجی را دقیقاً به فرمت زیر برگردان:
                [{{"question":"متن سوال", "options":["گزینه1","گزینه2","گزینه3","گزینه4"], "correct_answer":0}}]
                اگر سوالی پیدا نشد، فقط [] برگردان.
                متن: {text}
                """
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "تو یک دستیار هوشمندی که سوالات آزمون رو استخراج میکنی."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1
                )
                res = response.choices[0].message.content.strip()
                if res.startswith("```json"):
                    res = res[7:-3]
                data = json.loads(res)
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        
        return questions
