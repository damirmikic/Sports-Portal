import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = "users.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_premium INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def register_user(username, email, password):
    conn = get_connection()

    try:
        password_hash = generate_password_hash(password)

        conn.execute("""
            INSERT INTO users (username, email, password_hash)
            VALUES (?, ?, ?)
        """, (username, email, password_hash))

        conn.commit()
        return True, "Registracija uspešna."

    except sqlite3.IntegrityError:
        return False, "Korisničko ime ili email već postoje."

    finally:
        conn.close()


def login_user(email, password):
    conn = get_connection()

    user = conn.execute("""
        SELECT * FROM users
        WHERE email = ?
    """, (email,)).fetchone()

    conn.close()

    if user is None:
        return None

    if check_password_hash(user["password_hash"], password):
        return dict(user)

    return None
def is_user_premium(user_id):
    conn = get_connection()
    user = conn.execute("""
        SELECT is_premium FROM users
        WHERE id = ?
    """, (user_id,)).fetchone()
    conn.close()

    if user is None:
        return False

    return bool(user["is_premium"])