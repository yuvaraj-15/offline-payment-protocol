import sqlite3
import os
from contextlib import contextmanager

from shared.paths import BANK_DB_PATH  # type: ignore[import]

DB_PATH = str(BANK_DB_PATH)

def init_db(reset: bool = False):
    
    BANK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON;")

    if reset:
        cursor.execute("DROP TABLE IF EXISTS tokens;")
        cursor.execute("DROP TABLE IF EXISTS accounts;")

    # Accounts Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        user_id TEXT PRIMARY KEY,
        balance INTEGER NOT NULL CHECK(balance >= 0)
    );
    """)

    # Tokens Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tokens (
        token_id TEXT PRIMARY KEY,
        owner_id_hash TEXT NOT NULL,
        denomination INTEGER NOT NULL,
        issuer_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('ISSUED', 'SPENT', 'REFUNDED')),
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        spent_at INTEGER,
        refunded_at INTEGER,
        merchant_id TEXT
    );
    """)

    conn.commit()
    conn.close()

@contextmanager
def get_db_connection():
    
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()

def create_account(user_id: str, initial_balance: int = 0):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO accounts (user_id, balance) VALUES (?, ?)",
                (user_id, initial_balance),
            )
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error creating account: {e}")

def get_balance(user_id: str) -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM accounts WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return row[0]
    return 0
