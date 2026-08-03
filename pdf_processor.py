import re
import os
import base64
import json
from openai import OpenAI

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

try:
    import fitz  # pymupdf
except ImportError: fitz = None
try:
    from pdf2image import convert_from_path
except ImportError: convert_from_path = None
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
    def _image_to_base64(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode('utf-8')

    @staticmethod
    def extract_text_from_image_ai(image_path):
        """ارسال عکس به هوش مصنوعی بینایی Groq برای استخراج مستقیم سوالات"""
        if not GROQ_API_KEY:
            return ""
        try:
            client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            base64_img = FileProcessor._image_to_base64(image_path)
            
            response = client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "لطفاً سوالات و گزینه‌های موجود در این عکس را استخراج کن. فقط متن را برگردان و هیچ توضیح اضافه‌ای نده."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                        ]
                    }
                ],
                max_tokens=2048
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return ""

    @staticmethod
    def extract_text_from_pdf(file_path):
        # 1. تلاش با pymupdf (برای فایل‌های متنی)
        if fitz:
            try:
                doc = fitz.open(file_path)
                text = "".join([page.get_text() for page in doc])
                if len(text.strip()) > 50:
                    return FileProcessor._normalize_text(text)
            except: pass
        
        # 2. اگر متن پیدا نشد (یعنی اسکن شده است)،
        # فقط یک صفحه از فایل PDF را به عکس تبدیل کن و به هوش مصنوعی بفرست
        if convert_from_path and GROQ_API_KEY:
            try:
                images = convert_from_path(file_path, dpi=150, first_page=1, last_page=1)
                if images:
                    img_path = "temp_ai_scan.jpg"
                    images[0].save(img_path)
                    text = FileProcessor.extract_text_from_image_ai(img_path)
                    os.remove(img_path)
                    return text.strip()
            except: pass
        return ""

    @staticmethod
    def extract_text(file_path):
        if file_path.endswith('.docx'):
            if docx2txt:
                try: return docx2txt.process(file_path)
                except: return ""
        elif file_path.endswith('.pdf'):
            return FileProcessor.extract_text_from_pdf(file_path)
        else:
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f: return f.read()
            except: return ""

    @staticmethod
    def parse_questions_from_text(text):
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
