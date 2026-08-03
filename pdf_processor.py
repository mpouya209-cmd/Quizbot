import re
import gc
import os

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
        if PyPDF2 is None:
            raise ImportError("کتابخانه PyPDF2 نصب نیست! (pip install PyPDF2)")
        text = ""
        try:
            with open(file_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            return f"خطا در خواندن فایل PDF: {str(e)}"
        return text

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
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()

    @staticmethod
    def parse_questions_from_text(text):
        questions = []
        lines = text.split('\n')
        current_question = None
        current_options = []
        is_question = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            is_option = False
            option_match = re.match(r'^([الف-یa-zA-Z]|[0-9]+)[\.\-\:\)]\s*(.+)', line)
            if option_match and current_question:
                option_text = option_match.group(2).strip()
                if option_text and len(option_text) > 1 and len(option_text) < 100:
                    current_options.append(option_text)
                    is_option = True
                    continue
            question_match = re.match(r'^(\d+)[\.\-\:\)]\s*(.+)', line)
            if question_match:
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
            if current_question and not is_option:
                if not re.match(r'^[الف-یa-zA-Z0-9]', line):
                    current_question += " " + line
        
        if current_question and len(current_options) >= 2:
            questions.append({
                'question': current_question[:500],
                'options': current_options[:4],
                'correct_answer': 0
            })
        if not questions:
            questions = FileProcessor._smart_extract(text)
        if not questions:
            questions = FileProcessor._extract_with_pattern(text)
        return questions

    @staticmethod
    def _smart_extract(text):
        questions = []
        sentences = re.split(r'[\.\n\r]+', text)
        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            if '?' in sentence or '؟' in sentence or any(word in sentence.lower() for word in ['what', 'which', 'who', 'where', 'when', 'why', 'how', 'چی', 'کدام', 'کی', 'کجا', 'چرا', 'چگونه']):
                options = []
                for j in range(i+1, min(i+10, len(sentences))):
                    next_line = sentences[j].strip()
                    if not next_line:
                        continue
                    if re.match(r'^[الف-یa-zA-Z0-9]', next_line):
                        if any(word in next_line for word in ['الف', 'ب', 'ج', 'د', 'A', 'B', 'C', 'D', '1', '2', '3', '4']):
                            options.append(next_line)
                        elif len(next_line) < 50 and not any(word in next_line for word in ['what', 'which', 'how', 'چی', 'کدام']):
                            options.append(next_line)
                    else:
                        break
                if len(options) < 2:
                    for j in range(i+1, min(i+8, len(sentences))):
                        next_line = sentences[j].strip()
                        if next_line and len(next_line) < 60 and not any(word in next_line for word in ['what', 'which', 'how', 'چی', 'کدام', '?', '؟']):
                            options.append(next_line)
                        if len(options) >= 4:
                            break
                options = list(dict.fromkeys(options))
                if len(options) >= 2:
                    question_text = sentence
                    if len(question_text) < 20:
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
        questions = []
        pattern = r'(\d+)[\.\-\)]\s*(.*?)(?=\n\s*\d+[\.\-\)]|$)'
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            q_text = match[1].strip()
            options = []
            opt_pattern1 = r'([الف-ی])[\.\-\)]\s*([^\n\r]+)'
            opt_matches = re.findall(opt_pattern1, q_text)
            if opt_matches:
                options = [opt[1].strip() for opt in opt_matches]
            if not options:
                opt_pattern2 = r'([0-9]+)[\.\-\)]\s*([^\n\r]+)'
                opt_matches = re.findall(opt_pattern2, q_text)
                if opt_matches:
                    options = [opt[1].strip() for opt in opt_matches]
            if not options:
                opt_pattern3 = r'([A-Da-d])[\.\-\)]\s*([^\n\r]+)'
                opt_matches = re.findall(opt_pattern3, q_text)
                if opt_matches:
                    options = [opt[1].strip() for opt in opt_matches]
            if options and len(options) >= 2:
                question_part = q_text
                for opt in options:
                    opt_pattern = r'([الف-یa-zA-Z0-9])[\.\-\)]\s*' + re.escape(opt)
                    question_part = re.sub(opt_pattern, '', question_part)
                question_part = question_part.strip()
                if not question_part:
                    question_part = q_text
                questions.append({
                    'question': question_part[:500],
                    'options': options[:4],
                    'correct_answer': 0
                })
        return questions
