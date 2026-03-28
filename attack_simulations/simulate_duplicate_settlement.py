import os
import sys
import uuid
import time
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]
from shared.models import Token, TransactionPackage  # type: ignore[import]
from shared.crypto import sign_data, canonical_hash, verify_signature, derive_owner_hash  # type: ignore[import]
from shared.constants import ISSUER_ID, EXPIRY_SECONDS  # type: ignore[import]

LOG_PATH = os.path.join(os.path.dirname(__file__), "log_simulate_duplicate_settlement.txt")

def make_in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("""
        CREATE TABLE accounts (
            user_id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL CHECK(balance >= 0)
        )
    """)
    conn.execute("""
        CREATE TABLE tokens (
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
        )
    """)
    return conn

def settle_token(conn, token, merchant_id, private_key, public_key):
    now = int(time.time())
    c_hash = canonical_hash(token)
    if not verify_signature(public_key, c_hash, token.signature):
        return "REJECTED_INVALID_SIG"

    conn.execute("BEGIN IMMEDIATE")
    cursor = conn.execute(
        "UPDATE tokens SET status = 'SPENT', spent_at = ?, merchant_id = ? WHERE token_id = ? AND status = 'ISSUED'",
        (now, merchant_id, token.token_id)
    )
    if cursor.rowcount == 1:
        row = conn.execute("SELECT balance FROM accounts WHERE user_id = ?", (merchant_id,)).fetchone()
        if row:
            conn.execute("UPDATE accounts SET balance = ? WHERE user_id = ?", (row[0] + token.denomination, merchant_id))
        else:
            conn.execute("INSERT INTO accounts (user_id, balance) VALUES (?, ?)", (merchant_id, token.denomination))
        conn.commit()
        return "SETTLED"
    else:
        conn.rollback()
        row = conn.execute("SELECT status FROM tokens WHERE token_id = ?", (token.token_id,)).fetchone()
        if not row:
            return "REJECTED_UNKNOWN"
        return f"REJECTED_{row[0]}"

def run():
    lines = []

    def p(msg=""):
        print(msg)
        lines.append(msg)

    p("Scenario: Duplicate Settlement Attempt")
    p("-" * 40)

    p("Step 1: Generating ephemeral bank key pair ...")
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    p("         done")

    p("Step 2: Issuing a valid signed token ...")
    now = int(time.time())
    token = Token(
        token_id=str(uuid.uuid4()),
        issuer_id=ISSUER_ID,
        owner_id_hash=derive_owner_hash("alice"),
        denomination=100,
        issue_timestamp=now,
        expiry_timestamp=now + EXPIRY_SECONDS,
        signature=""
    )
    token.signature = sign_data(private_key, canonical_hash(token))
    p(f"         token_id: {token.token_id}")
    p("         done")

    p("Step 3: Inserting token into isolated in-memory ledger ...")
    conn = make_in_memory_db()
    conn.execute(
        "INSERT INTO tokens (token_id, owner_id_hash, denomination, issuer_id, status, created_at, expires_at) VALUES (?, ?, ?, ?, 'ISSUED', ?, ?)",
        (token.token_id, token.owner_id_hash, token.denomination, token.issuer_id, now, now + EXPIRY_SECONDS)
    )
    conn.commit()
    p("         done")

    merchant_id = "MerchantBeta"

    p("Step 4: Performing first settlement ...")
    result_1 = settle_token(conn, token, merchant_id, private_key, public_key)
    p(f"         Result: {result_1}")

    p("Step 5: Performing second settlement on same token ...")
    result_2 = settle_token(conn, token, merchant_id, private_key, public_key)
    p(f"         Result: {result_2}")

    conn.close()
    p()

    if result_1 == "SETTLED" and result_2.startswith("REJECTED"):
        p("Summary: Duplicate settlement simulation passed. Second attempt correctly rejected.")
    else:
        p(f"Summary: UNEXPECTED outcome. result_1={result_1}, result_2={result_2}")

    with open(LOG_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    run()