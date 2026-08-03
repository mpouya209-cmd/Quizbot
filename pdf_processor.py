import re
import os
import json
import google.generativeai as genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

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
        text = re.sub(r'(\s*)([ا-ی])(\s*)([ا-ی])(\s*)', r'\2\4', text)
        text = re.sub(r'\s+([\.\-\:\)\.,])', r'\1', text)
        return text.strip()

    @staticmethod
    def extract_text(file_path):
        if file_path.endswith('.docx'):
            if docx2txt:
                try: return docx2txt.process(file_path)
                except: return ""
        elif file_path.endswith('.pdf'):
            # ... (کد PDF که قبلاً بود) ...
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
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    return f.read()
            except:
                return ""

    @staticmethod
    def parse_questions_from_text(text):
        # 1. اگر هوش مصنوعی گوگل فعال بود، استفاده کن
        if GEMINI_API_KEY:
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel('gemini-1.5-flash')
                prompt = f"""
                متن زیر سوالات یک آزمون است.
                لطفاً سوالات و گزینه‌ها را به فرمت دقیق JSON زیر استخراج کن.
                اگر سوالی پیدا نشد، [] برگردان.
                فرمت: [{{"question":"...", "options":["...","...","...","..."], "correct_answer":0}}]
                متن: {text}
                """
                response = model.generate_content(prompt)
                res = response.text.strip()
                if res.startswith("```json"): res = res[7:-3]
                data = json.loads(res)
                if isinstance(data, list): return data
            except Exception:
                pass
        
        # 2. روش قدیمی و قدرتمند (برای فایل‌های DOCX و متون ساده)
        questions = []
        lines = text.split('\n')
        current_q = None
        current_opts = []
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # تشخیص سوالات شماره‌دار
            q_match = re.match(r'^\s*(\d+)\s*[\.\-\:\)]\s*(.*)', line)
            # تشخیص گزینه‌ها (حتی اگر شماره‌گذاری نامرتب باشه)
            o_match = re.match(r'^\s*([الف-ی]|[0-9]|[A-Da-d])\s*[\.\-\:\)]\s*(.*)', line)

            if q_match:
                if current_q and len(current_opts) >= 2:
                    questions.append({"question": current_q[:500], "options": current_opts[:4], "correct_answer": 0})
                current_q = q_match.group(2).strip()
                current_opts = []
            elif o_match and current_q:
                current_opts.append(o_match.group(2).strip())
            elif current_q and not o_match and not re.match(r'^\s*[0-9]', line):
                current_q += " " + line
        
        if current_q and len(current_opts) >= 2:
            questions.append({"question": current_q[:500], "options": current_opts[:4], "correct_answer": 0})
        
        return questions
