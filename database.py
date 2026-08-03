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
        self.conn.commit()

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

    def close(self):
        self.conn.close()
