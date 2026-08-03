import re
import os
import gc

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
        """
        این تابع متن استخراج شده از OCR را نرمال‌سازی می‌کند.
        مثلاً اگر OCR حروف رو با فاصله جدا کرده باشه (ا لف) ، اصلاحش می‌کنه.
        """
        # اصلاح فاصله‌های اضافی بین حروف فارسی (مشکل رایج Tesseract)
        text = re.sub(r'(\s*)([ا-ی])(\s*)([ا-ی])(\s*)', r'\2\4', text)
        # حذف فاصله‌های اضافی و خطوط خالی تکراری
        text = re.sub(r'\n\s*\n', '\n', text)
        return text

    @staticmethod
    def extract_text_from_docx(file_path):
        if docx2txt is None:
            return ""
        try:
            return docx2txt.process(file_path)
        except Exception:
            return ""

    @staticmethod
    def extract_text_from_pdf(file_path):
        text = ""
        if fitz:
            try:
                doc = fitz.open(file_path)
                for page in doc:
                    text += page.get_text()
                if len(text.strip()) > 50:
                    return FileProcessor._normalize_text(text)
            except Exception:
                pass

        if PyPDF2:
            try:
                with open(file_path, 'rb') as file:
                    reader = PyPDF2.PdfReader(file)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                if len(text.strip()) > 50:
                    return FileProcessor._normalize_text(text)
            except Exception:
                pass

        # OCR برای فایل‌های اسکن شده
        if convert_from_path and pytesseract:
            try:
                images = convert_from_path(file_path)
                for img in images:
                    text += pytesseract.image_to_string(img, lang='fas+eng') + "\n"
                return FileProcessor._normalize_text(text)
            except Exception:
                return ""

        return ""

    @staticmethod
    def extract_text(file_path):
        if file_path.endswith('.docx'):
            return FileProcessor.extract_text_from_docx(file_path)
        elif file_path.endswith('.pdf'):
            return FileProcessor.extract_text_from_pdf(file_path)
        else:
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    return f.read()
            except UnicodeDecodeError:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except:
                    return ""

    @staticmethod
    def parse_questions_from_text(text):
        # مرحله 1: نرمال‌سازی متن OCR شده
        text = FileProcessor._normalize_text(text)
        lines = text.split('\n')
        
        questions = []
        current_question = None
        current_options = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # تشخیص گزینه‌ها (با در نظر گرفتن فاصله‌های اضافی احتمالی)
            # الگو: الف) یا الف . یا 1) یا 1-
            option_match = re.match(r'^\s*([الف-ی]|[0-9]|[A-Da-d])\s*[\.\-\:\)]\s*(.+)', line)
            
            # تشخیص سوالات جدید با شماره (مثلاً 1- سوال... یا 1) سوال...)
            question_match = re.match(r'^\s*(\d+)\s*[\.\-\:\)]\s*(.+)', line)
            
            if question_match:
                # ذخیره سوال قبلی (اگر وجود داشت)
                if current_question and len(current_options) >= 2:
                    questions.append({
                        'question': current_question[:500],
                        'options': current_options[:4],
                        'correct_answer': 0
                    })
                
                # شروع سوال جدید
                current_question = question_match.group(2).strip()
                current_options = []
                continue
            
            # اگر خط، یک گزینه بود
            elif option_match and current_question:
                option_text = option_match.group(2).strip()
                # فیلتر کردن خطوط گزینه (که خیلی کوتاه یا نامربوط نباشن)
                if option_text and len(option_text) > 1 and len(option_text) < 100:
                    current_options.append(option_text)
                continue
            
            # اگر خط جدیدی بود و گزینه یا شماره سوال نبود، اما قبلاً سوال داشتیم
            elif current_question:
                # اگر خط با حرف یا عدد شروع نمیشد، بخشی از خود سوال هست
                if not re.match(r'^\s*[الف-یa-zA-Z0-9]', line):
                    current_question += " " + line

        # اضافه کردن سوال آخر
        if current_question and len(current_options) >= 2:
            questions.append({
                'question': current_question[:500],
                'options': current_options[:4],
                'correct_answer': 0
            })

        return questions
