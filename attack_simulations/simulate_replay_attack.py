import os
import sys
import uuid
import time
import dataclasses
import json
import sqlite3
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]
from shared.models import Token, TransactionPackage  # type: ignore[import]
from shared.crypto import sign_data, canonical_hash, verify_signature, derive_owner_hash  # type: ignore[import]
from shared.constants import ISSUER_ID, EXPIRY_SECONDS  # type: ignore[import]

LOG_PATH = os.path.join(os.path.dirname(__file__), "log_simulate_replay_attack.txt")

def make_in_memory_merchant_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
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
    conn.commit()
    return conn

def save_transaction(conn, packet):
    tx_id = packet["transaction_id"]
    tokens = packet["tokens"]
    total = sum(t["denomination"] for t in tokens)
    try:
        conn.execute(
            "INSERT INTO transactions (transaction_id, buyer_id_hash, merchant_id, total_amount, timestamp, requested_amount, buyer_display_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tx_id, packet["buyer_id_hash"], packet["merchant_id"], total, packet["transaction_timestamp"], packet["requested_amount"], packet.get("buyer_display_name", ""))
        )
        for t in tokens:
            conn.execute(
                "INSERT INTO received_tokens (token_id, transaction_id, token_json, expiry_ts) VALUES (?, ?, ?, ?)",
                (t["token_id"], tx_id, json.dumps(t), t["expiry_timestamp"])
            )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False

def run():
    lines = []

    def p(msg=""):
        print(msg)
        lines.append(msg)

    p("Scenario: Merchant Replay Attack")
    p("-" * 40)

    p("Step 1: Generating ephemeral key pair ...")
    private_key = ec.generate_private_key(ec.SECP256R1())
    p("         done")

    p("Step 2: Building a signed token and transaction packet ...")
    now = int(time.time())
    token = Token(
        token_id=str(uuid.uuid4()),
        issuer_id=ISSUER_ID,
        owner_id_hash=derive_owner_hash("bob"),
        denomination=50,
        issue_timestamp=now,
        expiry_timestamp=now + EXPIRY_SECONDS,
        signature=""
    )
    token.signature = sign_data(private_key, canonical_hash(token))

    packet = {
        "transaction_id": str(uuid.uuid4()),
        "buyer_id_hash": token.owner_id_hash,
        "merchant_id": "MerchantGamma",
        "tokens": [dataclasses.asdict(token)],
        "transaction_timestamp": now,
        "requested_amount": 50,
        "buyer_display_name": "Bob"
    }
    p("         done")

    p("Step 3: Setting up isolated in-memory merchant database ...")
    conn = make_in_memory_merchant_db()
    p("         done")

    p("Step 4: Sending packet to merchant (first attempt) ...")
    result_1 = save_transaction(conn, packet)
    p(f"         Result: {'ACCEPTED' if result_1 else 'REJECTED'}")

    p("Step 5: Replaying identical packet to merchant (second attempt) ...")
    result_2 = save_transaction(conn, packet)
    p(f"         Result: {'ACCEPTED' if result_2 else 'REJECTED - duplicate transaction_id/token_id detected'}")

    conn.close()
    p()

    if result_1 and not result_2:
        p("Summary: Replay attack simulation passed. Second identical packet rejected by PRIMARY KEY constraint.")
    else:
        p(f"Summary: UNEXPECTED outcome. result_1={result_1}, result_2={result_2}")

    with open(LOG_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    run()