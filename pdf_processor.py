import re
import os
import json
import google.generativeai as genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import docx2txt
except ImportError:
    docx2txt = None


class FileProcessor:
    @staticmethod
    def _normalize_text(text):
        # اصلاح فاصله‌های اضافی بین حروف
        text = re.sub(r'(\s*)([ا-ی])(\s*)([ا-ی])(\s*)', r'\2\4', text)
        # حذف فاصله‌های اضافی
        text = re.sub(r'\s+([\.\-\:\)\.,])', r'\1', text)
        # حذف خطوط خالی تکراری
        text = re.sub(r'\n\s*\n', '\n', text)
        return text.strip()

    @staticmethod
    def extract_text_from_docx(file_path):
        if docx2txt is None: return ""
        try: return docx2txt.process(file_path)
        except Exception: return ""

    @staticmethod
    def extract_text_from_pdf(file_path):
        text = ""
        if fitz:
            try:
                doc = fitz.open(file_path)
                for page in doc: text += page.get_text()
                if len(text.strip()) > 50: return FileProcessor._normalize_text(text)
            except Exception: pass
        if PyPDF2:
            try:
                with open(file_path, 'rb') as file:
                    reader = PyPDF2.PdfReader(file)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text: text += page_text + "\n"
                if len(text.strip()) > 50: return FileProcessor._normalize_text(text)
            except Exception: pass
        if convert_from_path and pytesseract:
            try:
                images = convert_from_path(file_path)
                for img in images:
                    text += pytesseract.image_to_string(img, lang='fas+eng') + "\n"
                return FileProcessor._normalize_text(text)
            except Exception: return ""
        return ""

    @staticmethod
    def extract_text(file_path):
        if file_path.endswith('.docx'): return FileProcessor.extract_text_from_docx(file_path)
        elif file_path.endswith('.pdf'): return FileProcessor.extract_text_from_pdf(file_path)
        else:
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f: return f.read()
            except:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f: return f.read()
                except: return ""

    @staticmethod
    def parse_questions_from_text(text):
        """استفاده از Gemini رایگان برای استخراج هوشمند سوالات"""
        if not GEMINI_API_KEY:
            # اگر کلید نباشد، به روش قدیمی برمی‌گردیم
            return FileProcessor._fallback_extract(text)

        try:
            # تنظیم مدل رایگان گوگل
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            prompt = f"""
            متن زیر شامل سوالات یک آزمون فارسی است.
            لطفاً تمام سوالات و گزینه‌های مربوط به هر سوال را استخراج کن.
            خروجی را دقیقاً در قالب JSON زیر برگردان:
            [{{"question": "متن سوال", "options": ["گزینه ۱", "گزینه ۲", "گزینه ۳", "گزینه ۴"], "correct_answer": 0}}]
            اگر متن سوالی نداشت، فقط یک لیست خالی [] برگردان.
            متن:
            {text}
            """
            
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            
            # پاکسازی مارک‌داون اضافی هوش مصنوعی
            if result_text.startswith("```json"): result_text = result_text[7:]
            if result_text.endswith("```"): result_text = result_text[:-3]
            
            data = json.loads(result_text)
            if isinstance(data, list):
                return data
            return []
            
        except Exception as e:
            print(f"خطای هوش مصنوعی رایگان گوگل: {e}")
            return FileProcessor._fallback_extract(text)

    @staticmethod
    def _fallback_extract(text):
        """روش قدیمی (اگر هوش مصنوعی کار نکرد)"""
        questions = []
        lines = text.split('\n')
        current_question = None
        current_options = []
        for line in lines:
            line = line.strip()
            if not line: continue
            option_match = re.match(r'^\s*([الف-ی]|[0-9]|[A-Da-d])\s*[\.\-\:\)]\s*(.+)', line)
            if option_match and current_question:
                current_options.append(option_match.group(2).strip())
                continue
            question_match = re.match(r'^\s*(\d+)\s*[\.\-\:\)]\s*(.+)', line)
            if question_match:
                if current_question and len(current_options) >= 2:
                    questions.append({'question': current_question[:500], 'options': current_options[:4], 'correct_answer': 0})
                current_question = question_match.group(2).strip()
                current_options = []
                continue
            if current_question and not option_match:
                current_question += " " + line
        if current_question and len(current_options) >= 2:
            questions.append({'question': current_question[:500], 'options': current_options[:4], 'correct_answer': 0})
        return questions
