import re
import os
from openai import OpenAI

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

try:
    import fitz
except ImportError: fitz = None
try:
    from pdf2image import convert_from_path
except ImportError: convert_from_path = None
try:
    import pytesseract
except ImportError: pytesseract = None
try:
    import PyPDF2
except ImportError: PyPDF2 = None
try:
    import docx2txt
except ImportError: docx2txt = None


class FileProcessor:
    @staticmethod
    def _normalize_text(text):
        # اصلاح فاصله‌های اضافی بین حروف فارسی (مشکل OCR)
        text = re.sub(r'(\s*)([ا-ی])(\s*)([ا-ی])(\s*)', r'\2\4', text)
        # اصلاح فاصله قبل از نقطه‌گذاری
        text = re.sub(r'\s+([\.\-\:\)\.,])', r'\1', text)
        return text.strip()

    @staticmethod
    def extract_text(file_path):
        if file_path.endswith('.docx'):
            if docx2txt:
                try: return docx2txt.process(file_path)
                except: return ""
        elif file_path.endswith('.pdf'):
            if fitz:
                try:
                    doc = fitz.open(file_path)
                    text = "".join([page.get_text() for page in doc])
                    return FileProcessor._normalize_text(text)
                except: pass
            if PyPDF2:
                try:
                    text = ""
                    with open(file_path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        for page in reader.pages:
                            text += page.extract_text() or ""
                    return FileProcessor._normalize_text(text)
                except: pass
            if convert_from_path and pytesseract:
                try:
                    text = ""
                    for img in convert_from_path(file_path):
                        text += pytesseract.image_to_string(img, lang='fas+eng') + "\n"
                    return FileProcessor._normalize_text(text)
                except: pass
            return ""
        else:
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f: return f.read()
            except: return ""

    @staticmethod
    def parse_questions_from_text(text):
        # === مرحله ۱: تلاش با هوش مصنوعی Groq ===
        if GROQ_API_KEY:
            try:
                client = OpenAI(
                    api_key=GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1"
                )
                prompt = f"""
                متن زیر یک آزمون است. لطفاً سوالات و ۴ گزینه را استخراج کن.
                خروجی را دقیقاً به فرمت JSON زیر برگردان:
                [{{"question":"متن سوال", "options":["گزینه1","گزینه2","گزینه3","گزینه4"], "correct_answer":0}}]
                اگر سوالی پیدا نشد [] برگردان.
                متن: {text}
                """
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "تو یک دستیار هوشمندی که سوالات آزمون رو استخراج میکنی."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                )
                res = response.choices[0].message.content.strip()
                # پاکسازی مارک‌داون احتمالی
                if res.startswith("```json"): res = res[7:-3]
                import json
                data = json.loads(res)
                if isinstance(data, list): return data
            except Exception:
                pass  # اگر خطا رخ داد، به مرحله بعد می‌رود

        # === مرحله ۲: روش قدیمی (Regex) ===
        # این روش زمانی استفاده می‌شود که هوش مصنوعی کار نکند
        questions = []
        lines = text.split('\n')
        current_q = None
        current_opts = []
        for line in lines:
            line = line.strip()
            if not line: continue
            q_match = re.match(r'^\s*(\d+)\s*[\.\-\:\)]\s*(.*)', line)
            o_match = re.match(r'^\s*([الف-ی]|[0-9]|[A-Da-d])\s*[\.\-\:\)]\s*(.*)', line)
            if q_match:
                if current_q and len(current_opts) >= 2:
                    questions.append({"question": current_q[:500], "options": current_opts[:4], "correct_answer": 0})
                current_q = q_match.group(2).strip()
                current_opts = []
            elif o_match and current_q:
                current_opts.append(o_match.group(2).strip())
            elif current_q and not q_match and not o_match:
                current_q += " " + line
        if current_q and len(current_opts) >= 2:
            questions.append({"question": current_q[:500], "options": current_opts[:4], "correct_answer": 0})
        return questions
