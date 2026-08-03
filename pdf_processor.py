import re
import gc
import os

# تلاش برای ایمپورت کتابخانه‌های جدید و قدیمی
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
    def extract_text_from_docx(file_path):
        if docx2txt is None:
            raise ImportError("کتابخانه docx2txt نصب نیست! (pip install docx2txt)")
        try:
            text = docx2txt.process(file_path)
            return text
        except Exception as e:
            return f"خطا در خواندن فایل Word: {str(e)}"

    @staticmethod
    def extract_text_from_pdf(file_path):
        """استخراج متن از PDF، حتی اگر قفل شده یا اسکن شده باشد"""
        text = ""
        
        # 1. تلاش با pymupdf (بسیار سریع و قدرتمند برای فایل‌های قفل شده)
        if fitz:
            try:
                doc = fitz.open(file_path)
                for page in doc:
                    text += page.get_text()
                doc.close()
                # اگر متن حداقل ۵۰ کاراکتر داشت، یعنی موفق بوده و برمی‌گردونیم
                if len(text.strip()) > 50:
                    return text
            except Exception:
                pass

        # 2. تلاش با PyPDF2 (اگر pymupdf کار نکرد)
        if PyPDF2:
            try:
                with open(file_path, 'rb') as file:
                    reader = PyPDF2.PdfReader(file)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                if len(text.strip()) > 50:
                    return text
            except Exception:
                pass

        # 3. اگر متن پیدا نشد، یعنی فایل اسکن شده است => OCR
        if convert_from_path and pytesseract:
            try:
                # تبدیل صفحات PDF به عکس و تشخیص متن با Tesseract
                images = convert_from_path(file_path)
                for img in images:
                    text += pytesseract.image_to_string(img, lang='eng+fas') + "\n"
                return text
            except Exception as e:
                return f"خطا در OCR: {str(e)}"
        
        return "متن قابل استخراج نبود (فایل اسکن شده و OCR نصب نیست)."

    @staticmethod
    def extract_text(file_path):
        if file_path.endswith('.docx'):
            return FileProcessor.extract_text_from_docx(file_path)
        elif file_path.endswith('.pdf'):
            return FileProcessor.extract_text_from_pdf(file_path)
        else:
            # استفاده از utf-8-sig برای جلوگیری از خطای BOM در فایل‌های متنی
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    return f.read()
            except UnicodeDecodeError:
                # اگر با utf-8-sig باز نشد، سعی میکنیم با utf-8 باز کنیم
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()

    @staticmethod
    def parse_questions_from_text(text):
        questions = []
        
        # روش 1: جستجوی سوالات با الگوی شماره
        lines = text.split('\n')
        current_question = None
        current_options = []
        is_question = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # چک کردن اینکه خط سوال هست یا گزینه
            is_option = False
            
            # الگوی گزینه (الف، ب، ج، د یا 1، 2، 3، 4 یا A، B، C، D)
            option_match = re.match(r'^([الف-یa-zA-Z]|[0-9]+)[\.\-\:\)]\s*(.+)', line)
            if option_match and current_question:
                option_text = option_match.group(2).strip()
                if option_text and len(option_text) > 1 and len(option_text) < 100:
                    current_options.append(option_text)
                    is_option = True
                    continue
            
            # الگوی سوال با شماره
            question_match = re.match(r'^(\d+)[\.\-\:\)]\s*(.+)', line)
            if question_match:
                # ذخیره سوال قبلی
                if current_question and len(current_options) >= 2:
                    questions.append({
                        'question': current_question[:500],
                        'options': current_options[:4],
                        'correct_answer': 0
                    })
                
                current_question = question_match.group(2).strip()
                current_options = []
                is_question = True
                continue
            
            # اگر خط جدیدی بود که با حرف یا عدد شروع نمیشد، ولی سوال داشتیم
            if current_question and not is_option:
                # اگر خط جدید شبیه گزینه نبود، به سوال اضافه کن
                if not re.match(r'^[الف-یa-zA-Z0-9]', line):
                    current_question += " " + line
        
        # ذخیره آخرین سوال
        if current_question and len(current_options) >= 2:
            questions.append({
                'question': current_question[:500],
                'options': current_options[:4],
                'correct_answer': 0
            })
        
        # روش 2: اگر سوالی پیدا نشد، از روش هوشمند استفاده کن
        if not questions:
            questions = FileProcessor._smart_extract(text)
        
        # روش 3: اگر بازم سوالی پیدا نشد، از روش الگو استفاده کن
        if not questions:
            questions = FileProcessor._extract_with_pattern(text)
        
        return questions

    @staticmethod
    def _smart_extract(text):
        """استخراج هوشمند سوالات از متن"""
        questions = []
        
        # پیدا کردن جملات سوالی (با ؟ یا ?)
        sentences = re.split(r'[\.\n\r]+', text)
        
        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # اگر جمله سوالی بود (؟ یا ? یا question words)
            if '?' in sentence or '؟' in sentence or any(word in sentence.lower() for word in ['what', 'which', 'who', 'where', 'when', 'why', 'how', 'چی', 'کدام', 'کی', 'کجا', 'چرا', 'چگونه']):
                
                # پیدا کردن گزینه‌های نزدیک به سوال
                options = []
                
                # نگاه به خطوط بعدی برای پیدا کردن گزینه‌ها
                for j in range(i+1, min(i+10, len(sentences))):
                    next_line = sentences[j].strip()
                    if not next_line:
                        continue
                    
                    # اگر خط بعدی با حروف الفبا یا اعداد شروع میشد و شبیه گزینه بود
                    if re.match(r'^[الف-یa-zA-Z0-9]', next_line):
                        # اگر شامل کلمات کلیدی گزینه بود
                        if any(word in next_line for word in ['الف', 'ب', 'ج', 'د', 'A', 'B', 'C', 'D', '1', '2', '3', '4']):
                            options.append(next_line)
                        elif len(next_line) < 50 and not any(word in next_line for word in ['what', 'which', 'how', 'چی', 'کدام']):
                            options.append(next_line)
                    else:
                        break
                
                # اگر گزینه‌ها کم بود، از کل متن اطراف استفاده کن
                if len(options) < 2:
                    # پیدا کردن 4 خط بعدی که شبیه گزینه هستند
                    for j in range(i+1, min(i+8, len(sentences))):
                        next_line = sentences[j].strip()
                        if next_line and len(next_line) < 60 and not any(word in next_line for word in ['what', 'which', 'how', 'چی', 'کدام', '?', '؟']):
                            options.append(next_line)
                        if len(options) >= 4:
                            break
                
                # حذف گزینه‌های تکراری
                options = list(dict.fromkeys(options))
                
                if len(options) >= 2:
                    # ساخت سوال
                    question_text = sentence
                    if len(question_text) < 20:
                        # اگر سوال کوتاه بود، خطوط بعدی رو هم اضافه کن
                        for k in range(i+1, min(i+4, len(sentences))):
                            if sentences[k].strip() and not any(word in sentences[k] for word in options):
                                question_text += " " + sentences[k].strip()
                                break
                    
                    questions.append({
                        'question': question_text[:500],
                        'options': options[:4],
                        'correct_answer': 0
                    })
        
        return questions

    @staticmethod
    def _extract_with_pattern(text):
        """روش الگو: استخراج با فرمت‌های مختلف"""
        questions = []
        
        # الگوی سوال با شماره
        pattern = r'(\d+)[\.\-\)]\s*(.*?)(?=\n\s*\d+[\.\-\)]|$)'
        matches = re.findall(pattern, text, re.DOTALL)
        
        for match in matches:
            q_text = match[1].strip()
            
            options = []
            
            # الگوی الف، ب، ج، د
            opt_pattern1 = r'([الف-ی])[\.\-\)]\s*([^\n\r]+)'
            opt_matches = re.findall(opt_pattern1, q_text)
            if opt_matches:
                options = [opt[1].strip() for opt in opt_matches]
            
            # الگوی 1، 2، 3، 4
            if not options:
                opt_pattern2 = r'([0-9]+)[\.\-\)]\s*([^\n\r]+)'
                opt_matches = re.findall(opt_pattern2, q_text)
                if opt_matches:
                    options = [opt[1].strip() for opt in opt_matches]
            
            # الگوی A، B، C، D
            if not options:
                opt_pattern3 = r'([A-Da-d])[\.\-\)]\s*([^\n\r]+)'
                opt_matches = re.findall(opt_pattern3, q_text)
                if opt_matches:
                    options = [opt[1].strip() for opt in opt_matches]
            
            if options and len(options) >= 2:
                question_part = q_text
                
                # *** اصلاح مهم: جایگزین کردن گزینه‌ها با استفاده از Regex به جای replace ساده ***
                for opt in options:
                    # این الگو، حرف یا عدد گزینه و علامت آن را به همراه خود گزینه از متن سوال حذف می‌کند
                    opt_pattern = r'([الف-یa-zA-Z0-9])[\.\-\)]\s*' + re.escape(opt)
                    question_part = re.sub(opt_pattern, '', question_part)
                
                # پاکسازی نهایی (حذف کاراکترهای اضافی از انتهای سوال)
                question_part = question_part.strip()
                
                # اگر پس از حذف گزینه‌ها، سوال خالی شد، کل متن اولیه را برگردان
                if not question_part:
                    question_part = q_text
                
                questions.append({
                    'question': question_part[:500],
                    'options': options[:4],
                    'correct_answer': 0
                })
        
        return questions
