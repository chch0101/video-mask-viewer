import sqlite3
import os
import datetime

# Railway Volume 지원을 위한 DB 경로 설정
DB_PATH = os.environ.get("DATABASE_PATH")
if not DB_PATH:
    if os.path.exists("/app/data"):
        DB_PATH = "/app/data/evaluations.db"
    else:
        DB_PATH = "evaluations.db"

# 필요시 디렉토리 생성
db_dir = os.path.dirname(os.path.abspath(DB_PATH))
if db_dir and not os.path.exists(db_dir):
    try:
        os.makedirs(db_dir, exist_ok=True)
    except:
        pass

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Users Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS Users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            picture TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Evaluations logs
    c.execute('''
        CREATE TABLE IF NOT EXISTS Evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            video_name TEXT NOT NULL,
            mask_source TEXT,
            filename TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES Users(id)
        )
    ''')
    conn.commit()
    conn.close()

def upsert_user(user_id, email, name, picture):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO Users (id, email, name, picture)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            picture=excluded.picture
    ''', (user_id, email, name, picture))
    conn.commit()
    conn.close()

def log_evaluation(user_id, video_name, mask_source, filename):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO Evaluations (user_id, video_name, mask_source, filename)
        VALUES (?, ?, ?, ?)
    ''', (user_id, video_name, mask_source, filename))
    conn.commit()
    conn.close()

def get_user_evaluation_count(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM Evaluations WHERE user_id = ?', (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count


# ─────────────────────────── Admin Functions ───────────────────────────

def get_all_users():
    """모든 사용자 목록 조회"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM Users ORDER BY created_at DESC')
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_all_evaluations(user_id=None, search=None):
    """모든 평가 데이터 조회 (필터링 지원)"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    query = '''
        SELECT e.*, u.name as user_name, u.email
        FROM Evaluations e
        JOIN Users u ON e.user_id = u.id
    '''
    params = []
    conditions = []

    if user_id:
        conditions.append('e.user_id = ?')
        params.append(user_id)
    if search:
        conditions.append('(e.video_name LIKE ? OR e.filename LIKE ? OR e.mask_source LIKE ?)')
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    query += ' ORDER BY e.created_at DESC'

    c.execute(query, params)
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_stats():
    """대시보드용 통계"""
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM Users')
    user_count = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM Evaluations')
    eval_count = c.fetchone()[0]
    conn.close()
    return {'user_count': user_count, 'eval_count': eval_count}


if __name__ == "__main__":
    init_db()
    print("Database Initialized")
