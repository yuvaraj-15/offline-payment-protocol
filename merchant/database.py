"""Merchant Database (Plaintext Transaction Log).

Stores received offline transactions and tokens key-value.
Strictly relies on PRIMARY KEY constraints for duplicate detection.
"""
import sqlite3
import json
from contextlib import contextmanager
from typing import Optional

from shared.paths import MERCHANT_DB_PATH  # type: ignore[import]

DB_PATH = str(MERCHANT_DB_PATH)

@contextmanager
def get_db():
    MERCHANT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(reset: bool = False):
    """Initialize Merchant Ledger."""
    with get_db() as conn:
        if reset:
            conn.execute("DROP TABLE IF EXISTS config")
            conn.execute("DROP TABLE IF EXISTS received_tokens")
            conn.execute("DROP TABLE IF EXISTS transactions")

        # Transaction Log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                buyer_id_hash TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                total_amount INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                status TEXT DEFAULT 'PENDING',
                requested_amount INTEGER NOT NULL DEFAULT 0,
                buyer_display_name TEXT
            )
        """)
        
        # Safe migration for existing tables:
        try:
            conn.execute("ALTER TABLE transactions ADD COLUMN requested_amount INT DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column likely exists
            
        try:
            conn.execute("ALTER TABLE transactions ADD COLUMN buyer_display_name TEXT")
        except sqlite3.OperationalError:
            pass  # Column likely exists

        # Token Store
        # token_id is PRIMARY KEY to enforce global uniqueness
        # If the same token is presented twice (even in diff transactions), it fails.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS received_tokens (
                token_id TEXT PRIMARY KEY,
                transaction_id TEXT NOT NULL,
                token_json TEXT NOT NULL,
                expiry_ts INTEGER NOT NULL,
                status TEXT DEFAULT 'RECEIVED',
                FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

def load_config(key_name: str) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key_name,)).fetchone()
        return row["value"] if row else None

def save_config(key_name: str, value: str):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key_name, value))
        conn.commit()


def save_transaction(packet: dict) -> bool:
    """Atomically save a verified transaction package.

    Returns:
        True: Transaction committed.
        False: Duplicate token detected (Rolled back).
    """
    tx_id = packet["transaction_id"]
    buyer_hash = packet["buyer_id_hash"]
    m_id = packet["merchant_id"]
    ts = packet["transaction_timestamp"]
    req_amount = packet["requested_amount"]
    buyer_name = packet.get("buyer_display_name", "Unknown Customer")
    tokens = packet["tokens"]
    
    total = sum(t["denomination"] for t in tokens)
    
    with get_db() as conn:
        try:
            # 1. Insert Transaction Record
            conn.execute("""
                INSERT INTO transactions 
                (transaction_id, buyer_id_hash, merchant_id, total_amount, timestamp, requested_amount, buyer_display_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (tx_id, buyer_hash, m_id, total, ts, req_amount, buyer_name))
            
            # 2. Insert Tokens
            # This loop will FAIL with IntegrityError if ANY token_id exists
            for t in tokens:
                conn.execute("""
                    INSERT INTO received_tokens
                    (token_id, transaction_id, token_json, expiry_ts)
                    VALUES (?, ?, ?, ?)
                """, (t["token_id"], tx_id, json.dumps(t), t["expiry_timestamp"]))
                
            conn.commit()
            return True
            
        except sqlite3.IntegrityError:
            # Duplicate ID detected (Transaction level or Token level)
            conn.rollback()
            return False
        except sqlite3.Error:
            conn.rollback()
            raise
    return False  # unreachable; satisfies Pyre2 missing-return check
