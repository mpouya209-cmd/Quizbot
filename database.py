import sqlite3
import json
import os
import asyncio

class Database:
    def __init__(self, db_name="quiz.db"):
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        db_path = os.path.join(data_dir, db_name)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.lock = asyncio.Lock()
        self.create_tables()

    def create_tables(self):
        # جداول تکی (دست نخورده)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quiz_id TEXT,
                question TEXT,
                options TEXT,
                correct_answer INTEGER,
                category TEXT
            )
        """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_id ON questions(quiz_id)")
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_scores (
                user_id INTEGER,
                quiz_id TEXT,
                score INTEGER,
                total INTEGER,
                answers TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, quiz_id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_sessions (
                user_id INTEGER PRIMARY KEY,
                quiz_id TEXT,
                current_question INTEGER,
                answers TEXT,
                start_time DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # ===== جداول جدید مخصوص گروه (فقط اینا اضافه شدن) =====
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_sessions (
                chat_id INTEGER PRIMARY KEY,
                quiz_id TEXT,
                current_question INTEGER,
                start_time DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_answers (
                chat_id INTEGER,
                user_id INTEGER,
                question_index INTEGER,
                selected_option INTEGER,
                PRIMARY KEY (chat_id, user_id, question_index)
            )
        """)
        self.conn.commit()

    # ===== متدهای تکی (دست نخورده) =====
    async def save_questions(self, quiz_id, questions):
        async with self.lock:
            data = []
            for q in questions:
                data.append((quiz_id, q['question'], json.dumps(q['options']), q['correct_answer'], q.get('category', '')))
            self.cursor.executemany("""
                INSERT INTO questions (quiz_id, question, options, correct_answer, category)
                VALUES (?, ?, ?, ?, ?)
            """, data)
            self.conn.commit()

    def get_questions(self, quiz_id):
        self.cursor.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,))
        rows = self.cursor.fetchall()
        questions = []
        for row in rows:
            questions.append({
                'id': row[0],
                'question': row[2],
                'options': json.loads(row[3]),
                'correct_answer': row[4]
            })
        return questions

    async def save_session(self, user_id, quiz_id, current_question, answers):
        async with self.lock:
            self.cursor.execute("""
                INSERT OR REPLACE INTO active_sessions (user_id, quiz_id, current_question, answers)
                VALUES (?, ?, ?, ?)
            """, (user_id, quiz_id, current_question, json.dumps(answers)))
            self.conn.commit()

    def get_session(self, user_id):
        self.cursor.execute("SELECT * FROM active_sessions WHERE user_id=?", (user_id,))
        row = self.cursor.fetchone()
        if row:
            return {
                'quiz_id': row[1],
                'current_question': row[2],
                'answers': json.loads(row[3])
            }
        return None

    async def save_score(self, user_id, quiz_id, score, total, answers):
        async with self.lock:
            self.cursor.execute("""
                INSERT OR REPLACE INTO user_scores (user_id, quiz_id, score, total, answers)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, quiz_id, score, total, json.dumps(answers)))
            self.conn.commit()

    # ===== متدهای جدید مخصوص گروه (فقط اینا اضافه شدن) =====
    async def save_group_session(self, chat_id, quiz_id, current_question):
        async with self.lock:
            self.cursor.execute("""
                INSERT OR REPLACE INTO group_sessions (chat_id, quiz_id, current_question)
                VALUES (?, ?, ?)
            """, (chat_id, quiz_id, current_question))
            self.conn.commit()

    def get_group_session(self, chat_id):
        self.cursor.execute("SELECT * FROM group_sessions WHERE chat_id=?", (chat_id,))
        row = self.cursor.fetchone()
        if row:
            return {
                'quiz_id': row[1],
                'current_question': row[2]
            }
        return None

    async def save_group_answer(self, chat_id, user_id, q_index, option):
        async with self.lock:
            self.cursor.execute("SELECT * FROM group_answers WHERE chat_id=? AND user_id=? AND question_index=?", (chat_id, user_id, q_index))
            if not self.cursor.fetchone():
                self.cursor.execute("""
                    INSERT INTO group_answers (chat_id, user_id, question_index, selected_option)
                    VALUES (?, ?, ?, ?)
                """, (chat_id, user_id, q_index, option))
                self.conn.commit()
                return True
            return False

    def get_group_answers(self, chat_id, q_index):
        self.cursor.execute("SELECT user_id, selected_option FROM group_answers WHERE chat_id=? AND question_index=?", (chat_id, q_index))
        return self.cursor.fetchall()

    def get_all_group_answers(self, chat_id, total_questions):
        self.cursor.execute("SELECT user_id, question_index, selected_option FROM group_answers WHERE chat_id=?", (chat_id,))
        rows = self.cursor.fetchall()
        result = {}
        for user_id, q_idx, opt in rows:
            if user_id not in result:
                result[user_id] = {}
            result[user_id][q_idx] = opt
        return result

    def close(self):
        self.conn.close()
