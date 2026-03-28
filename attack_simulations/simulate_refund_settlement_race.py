import os
import sys
import uuid
import time
import sqlite3
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]
from shared.models import Token  # type: ignore[import]
from shared.crypto import sign_data, canonical_hash, verify_signature, derive_owner_hash  # type: ignore[import]
from shared.constants import ISSUER_ID, EXPIRY_SECONDS  # type: ignore[import]

DB_PATH = os.path.join(os.path.dirname(__file__), "temp_race.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), "log_simulate_refund_settlement_race.txt")

def setup_db(token, buyer_id, now, expired_ts):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
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
    conn.execute("INSERT INTO accounts (user_id, balance) VALUES (?, ?)", (buyer_id, 1000))
    conn.execute("INSERT INTO accounts (user_id, balance) VALUES (?, ?)", ("MerchantDelta", 0))
    conn.execute(
        "INSERT INTO tokens (token_id, owner_id_hash, denomination, issuer_id, status, created_at, expires_at) VALUES (?, ?, ?, ?, 'ISSUED', ?, ?)",
        (token.token_id, token.owner_id_hash, token.denomination, token.issuer_id, now - 7200, expired_ts)
    )
    conn.commit()
    conn.close()

def attempt_settlement(token, merchant_id, public_key, outcome):
    now = int(time.time())
    c_hash = canonical_hash(token)
    if not verify_signature(public_key, c_hash, token.signature):
        outcome["settlement"] = "REJECTED_INVALID_SIG"
        return
    conn = sqlite3.connect(DB_PATH, timeout=5)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE tokens SET status = 'SPENT', spent_at = ?, merchant_id = ? WHERE token_id = ? AND status = 'ISSUED'",
            (now, merchant_id, token.token_id)
        )
        if cursor.rowcount == 1:
            row = conn.execute("SELECT balance FROM accounts WHERE user_id = ?", (merchant_id,)).fetchone()
            conn.execute("UPDATE accounts SET balance = ? WHERE user_id = ?", (row[0] + token.denomination, merchant_id))
            conn.commit()
            outcome["settlement"] = "SETTLED"
        else:
            conn.rollback()
            row = conn.execute("SELECT status FROM tokens WHERE token_id = ?", (token.token_id,)).fetchone()
            outcome["settlement"] = f"REJECTED_{row[0]}" if row else "REJECTED_UNKNOWN"
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        outcome["settlement"] = f"ERROR: {e}"
    finally:
        conn.close()

def attempt_refund(token, buyer_id, outcome):
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH, timeout=5)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status, expires_at, denomination, owner_id_hash FROM tokens WHERE token_id = ?",
            (token.token_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            outcome["refund"] = "FAILED_UNKNOWN"
            return
        status, expires_at, denomination, db_owner_hash = row
        if derive_owner_hash(buyer_id) != db_owner_hash:
            conn.rollback()
            outcome["refund"] = "FAILED_OWNER_MISMATCH"
            return
        if status != "ISSUED":
            conn.rollback()
            outcome["refund"] = f"FAILED_{status}"
            return
        if now <= expires_at:
            conn.rollback()
            outcome["refund"] = "FAILED_NOT_EXPIRED"
            return
        cursor = conn.execute(
            "UPDATE tokens SET status = 'REFUNDED', refunded_at = ? WHERE token_id = ? AND status = 'ISSUED'",
            (now, token.token_id)
        )
        if cursor.rowcount != 1:
            conn.rollback()
            outcome["refund"] = "FAILED_CONCURRENT_MODIFICATION"
            return
        acct = conn.execute("SELECT balance FROM accounts WHERE user_id = ?", (buyer_id,)).fetchone()
        conn.execute("UPDATE accounts SET balance = ? WHERE user_id = ?", (acct[0] + denomination, buyer_id))
        conn.commit()
        outcome["refund"] = "REFUNDED"
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        outcome["refund"] = f"ERROR: {e}"
    finally:
        conn.close()

def run():
    lines = []

    def p(msg=""):
        print(msg)
        lines.append(msg)

    p("Scenario: Concurrent Refund and Settlement Race")
    p("-" * 40)

    p("Step 1: Generating ephemeral bank key pair ...")
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    p("         done")

    p("Step 2: Issuing token eligible for refund ...")
    buyer_id = "alice"
    now = int(time.time())
    expired_ts = now - 3600
    token = Token(
        token_id=str(uuid.uuid4()),
        issuer_id=ISSUER_ID,
        owner_id_hash=derive_owner_hash(buyer_id),
        denomination=100,
        issue_timestamp=now - 7200,
        expiry_timestamp=expired_ts,
        signature=""
    )
    token.signature = sign_data(private_key, canonical_hash(token))
    p("         done")

    p("Step 3: Inserting token into temporary ledger ...")
    setup_db(token, buyer_id, now, expired_ts)
    p("         done")

    p("Step 4: Launching concurrent settlement and refund threads ...")
    outcome = {}
    t1 = threading.Thread(target=attempt_settlement, args=(token, "MerchantDelta", public_key, outcome))
    t2 = threading.Thread(target=attempt_refund, args=(token, buyer_id, outcome))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    p(f"         Settlement result : {outcome.get('settlement', 'N/A')}")
    p(f"         Refund result     : {outcome.get('refund', 'N/A')}")

    p("Step 5: Checking final token state in database ...")
    check_conn = sqlite3.connect(DB_PATH)
    final_row = check_conn.execute("SELECT status FROM tokens WHERE token_id = ?", (token.token_id,)).fetchone()
    check_conn.close()
    final_status = final_row[0] if final_row else "MISSING"
    p(f"         Final token status: {final_status}")

    os.remove(DB_PATH)
    p()

    settlement_ok = outcome.get("settlement") == "SETTLED"
    refund_ok = outcome.get("refund") == "REFUNDED"

    if settlement_ok and not refund_ok:
        p("Summary: Race resolved. Settlement won. Single state transition enforced.")
    elif refund_ok and not settlement_ok:
        p("Summary: Race resolved. Refund won. Single state transition enforced.")
    elif settlement_ok and refund_ok:
        p("Summary: UNEXPECTED - both operations claimed success. Protocol failure.")
    else:
        p(f"Summary: Both operations failed. settlement={outcome.get('settlement')}, refund={outcome.get('refund')}")

    with open(LOG_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    run()