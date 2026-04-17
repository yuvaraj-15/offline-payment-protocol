import sqlite3
import json
import time
from typing import List, Optional
from contextlib import contextmanager

from shared.models import Token
from wallet.crypto import encrypt_blob, decrypt_blob  

from shared.paths import WALLET_DB_PATH  

DB_PATH = str(WALLET_DB_PATH)

@contextmanager
def get_db():
    WALLET_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db(reset: bool = False):
    if reset:
        pass

    with get_db() as conn:
        if reset:
            conn.execute("DROP TABLE IF EXISTS config")
            conn.execute("DROP TABLE IF EXISTS tokens")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value BLOB
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                token_id TEXT PRIMARY KEY,
                status TEXT CHECK(status IN ('UNSPENT', 'SPENT', 'EXPIRED')),
                denomination INTEGER,
                expiry_ts INTEGER,
                payload BLOB
            )
        """)

def save_config(key_name: str, value_str: str, master_key: bytes):
    encrypted = encrypt_blob(master_key, value_str.encode("utf-8"))
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
            (key_name, encrypted)
        )

def has_config(key_name: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM config WHERE key = ?", (key_name,)
        ).fetchone()
        return row is not None
    return False

def load_config(key_name: str, master_key: bytes) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key_name,)).fetchone()
        if not row:
            return None
        from cryptography.exceptions import InvalidTag  # type: ignore[import]
        try:
            plaintext = decrypt_blob(master_key, row["value"])
            return plaintext.decode("utf-8")
        except InvalidTag:
            raise ValueError("Decryption failed. Wrong password?")

def store_tokens(tokens: List[Token], master_key: bytes):
    with get_db() as conn:
        conn.execute("BEGIN")
        for t in tokens:
            import dataclasses
            token_json = json.dumps(dataclasses.asdict(t))
            encrypted = encrypt_blob(master_key, token_json.encode("utf-8"))

            conn.execute("""
                INSERT OR IGNORE INTO tokens
                (token_id, status, denomination, expiry_ts, payload)
                VALUES (?, 'UNSPENT', ?, ?, ?)
            """, (t.token_id, t.denomination, t.expiry_timestamp, encrypted))
        conn.execute("COMMIT")

def expire_stale_tokens() -> int:
    now = int(time.time())
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE tokens SET status = 'EXPIRED' WHERE expiry_ts < ? AND status = 'UNSPENT'",
            (now,)
        )
        conn.execute("COMMIT")
        return cursor.rowcount
    return 0

def list_unspent_tokens(master_key: bytes) -> List[Token]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT payload FROM tokens WHERE status = 'UNSPENT'"
        ).fetchall()

    tokens = []
    for r in rows:
        json_bytes = decrypt_blob(master_key, r["payload"])
        data = json.loads(json_bytes)
        tokens.append(Token(**data))
    return tokens

def mark_tokens_spent(token_ids: List[str]) -> bool:
    with get_db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            placeholders = ",".join("?" for _ in token_ids)

            cursor = conn.execute(
                f"""
                UPDATE tokens
                SET status = 'SPENT'
                WHERE token_id IN ({placeholders})
                  AND status = 'UNSPENT'
                """,
                token_ids
            )

            if cursor.rowcount == len(token_ids):
                conn.execute("COMMIT")
                return True
            else:
                conn.execute("ROLLBACK")
                return False
        except sqlite3.Error as e:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise RuntimeError(f"Database error during mark_tokens_spent: {e}") from e
    return False
