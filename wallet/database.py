"""Wallet Database (Encrypted SQLite).

Handles local storage of confidential tokens and keys.
All sensitive data is encrypted at rest using the User's derived key.
"""
import sqlite3
import json
import time
from typing import List, Optional
from contextlib import contextmanager

from shared.models import Token  # type: ignore[import]
from wallet.crypto import encrypt_blob, decrypt_blob  # type: ignore[import]

DB_PATH = "wallet/wallet.db"

@contextmanager
def get_db():
    # isolation_level=None disables Python's implicit transaction management.
    # This is required so explicit BEGIN IMMEDIATE / COMMIT / ROLLBACK work correctly.
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(reset: bool = False):
    """Initialize the encrypted wallet database."""
    if reset:
        # In a real app, we might backup first. For this proto, we drop.
        pass  # We'll rely on DROP TABLE IF EXISTS below

    with get_db() as conn:
        if reset:
            conn.execute("DROP TABLE IF EXISTS config")
            conn.execute("DROP TABLE IF EXISTS tokens")

        # Config: Stores salt (plaintext) and encrypted user_id
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value BLOB
            )
        """)

        # Tokens: Stores encrypted token blobs
        # Metadata (expiry, denomination, status) is PLAINTEXT for strict querying
        # Payload is ENCRYPTED
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
    """Encrypt and save a config value (e.g., buyer_id)."""
    encrypted = encrypt_blob(master_key, value_str.encode("utf-8"))
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key_name, encrypted)
        )


def load_config(key_name: str, master_key: bytes) -> Optional[str]:
    """Load and decrypt a config value."""
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key_name,)).fetchone()
        if not row:
            return None
        try:
            plaintext = decrypt_blob(master_key, row["value"])
            return plaintext.decode("utf-8")
        except Exception:
            raise ValueError("Decryption failed. Wrong password?")


def store_tokens(tokens: List[Token], master_key: bytes):
    """Encrypt and store newly issued tokens.

    Status defaults to 'UNSPENT'.
    """
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
    """Sweep UNSPENT tokens whose expiry_ts < now and transition to EXPIRED.

    MUST be called before any balance display or payment selection.
    Returns: number of tokens transitioned to EXPIRED.
    """
    now = int(time.time())
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE tokens SET status = 'EXPIRED' WHERE expiry_ts < ? AND status = 'UNSPENT'",
            (now,)
        )
        conn.execute("COMMIT")
        return cursor.rowcount
    return 0  # unreachable; satisfies Pyre2 missing-return check


def list_unspent_tokens(master_key: bytes) -> List[Token]:
    """Retrieve and decrypt all UNSPENT tokens.

    Callers MUST call expire_stale_tokens() before this to ensure
    no expired tokens remain in UNSPENT status.
    """
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
    """Atomically mark tokens as SPENT.

    Uses BEGIN IMMEDIATE to acquire exclusive write lock.
    Strict Rule: Only transition UNSPENT -> SPENT.
    Returns: True if ALL requested tokens were successfully transitioned.
             False if ANY token was missing or not UNSPENT (full rollback).
    """
    with get_db() as conn:
        try:
            # BEGIN IMMEDIATE acquires a RESERVED lock immediately,
            # preventing concurrent writers from interleaving.
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
                # Mismatch: some tokens were not UNSPENT or missing.
                conn.execute("ROLLBACK")
                return False
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            return False
    return False  # unreachable; satisfies Pyre2 missing-return check
