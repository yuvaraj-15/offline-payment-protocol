import os
import sys
import time
import json
import uuid
import sqlite3
import dataclasses

protocol_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if protocol_root not in sys.path:
    sys.path.insert(0, protocol_root)

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]
from shared.models import Token, TransactionPackage  # type: ignore[import]
from shared.crypto import sign_data, verify_signature, canonical_hash, derive_owner_hash  # type: ignore[import]
from wallet.crypto import derive_key, encrypt_blob, decrypt_blob  # type: ignore[import]
from shared.constants import ISSUER_ID, EXPIRY_SECONDS  # type: ignore[import]

def run_benchmarks():
    print("Starting Performance Benchmarks...")
    print("==================================")
    
    # 1. Setup isolated memory artifacts
    print("[*] Generating ephemeral memory ECDSA keypair...")
    bank_private_key = ec.generate_private_key(ec.SECP256R1())
    bank_public_key = bank_private_key.public_key()
    
    buyer_id = "BenchBuyer-1234"
    owner_hash = derive_owner_hash(buyer_id)
    now = int(time.time())
    
    def generate_token(denom: int) -> Token:
        t = Token(
            token_id=str(uuid.uuid4()),
            issuer_id=ISSUER_ID,
            owner_id_hash=owner_hash,
            denomination=denom,
            issue_timestamp=now,
            expiry_timestamp=now + EXPIRY_SECONDS,
            signature=""
        )
        t.signature = sign_data(bank_private_key, canonical_hash(t))
        return t

    sample_token = generate_token(100)
    iterations = 1000
    results = []
    
    # --- ECDSA Signature Verification Time ---
    print(f"[*] Measuring ECDSA Verification Time ({iterations} iterations)...")
    c_hash = canonical_hash(sample_token)
    sig = sample_token.signature
    
    start_time = time.perf_counter()
    for _ in range(iterations):
        verify_signature(bank_public_key, c_hash, sig)
    end_time = time.perf_counter()
    
    ecdsa_avg_ms = ((end_time - start_time) * 1000) / iterations
    results.append(("ECDSA Token Validation", f"{ecdsa_avg_ms:.4f} ms"))
    
    # --- Batch Verification Time (5 and 10 tokens) ---
    batch_5 = [generate_token(10) for _ in range(5)]
    batch_10 = [generate_token(10) for _ in range(10)]
    
    print(f"[*] Measuring Batch Verification Time (5 tokens, {iterations} iterations)...")
    start_time = time.perf_counter()
    for _ in range(iterations):
        for t in batch_5:
            verify_signature(bank_public_key, canonical_hash(t), t.signature)
    end_time = time.perf_counter()
    batch_5_avg_ms = ((end_time - start_time) * 1000) / iterations
    results.append(("ECDSA Batch Validation (5x)", f"{batch_5_avg_ms:.4f} ms"))

    print(f"[*] Measuring Batch Verification Time (10 tokens, {iterations} iterations)...")
    start_time = time.perf_counter()
    for _ in range(iterations):
        for t in batch_10:
            verify_signature(bank_public_key, canonical_hash(t), t.signature)
    end_time = time.perf_counter()
    batch_10_avg_ms = ((end_time - start_time) * 1000) / iterations
    results.append(("ECDSA Batch Validation (10x)", f"{batch_10_avg_ms:.4f} ms"))
    
    # --- Settlement Atomic Update Time ---
    print(f"[*] Measuring Atomic SQLite UPDATES in-memory ({iterations} iterations)...")
    
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute('''
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
        );
    ''')
    
    test_ids = [str(uuid.uuid4()) for _ in range(iterations)]
    conn.execute("BEGIN IMMEDIATE")
    for tid in test_ids:
        conn.execute('''
            INSERT INTO tokens
            (token_id, owner_id_hash, denomination, issuer_id, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, 'ISSUED', ?, ?)
        ''', (tid, owner_hash, 50, ISSUER_ID, now, now + EXPIRY_SECONDS))
    conn.commit()
    
    start_time = time.perf_counter()
    for tid in test_ids:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE tokens SET status = 'SPENT', spent_at = ?, merchant_id = ? WHERE token_id = ? AND status = 'ISSUED'",
            (now, "MerchantMock123", tid)
        )
        conn.commit()
    end_time = time.perf_counter()
    
    db_update_avg_ms = ((end_time - start_time) * 1000) / iterations
    results.append(("SQLite Atomic Update", f"{db_update_avg_ms:.4f} ms"))
    conn.close()

    # --- AES-GCM Encrypt/Decrypt Time ---
    print(f"[*] Measuring AES-GCM times ({iterations} iterations)...")
    password = "benchmarkpwd123"
    aes_salt = os.urandom(16)
    aes_key, _ = derive_key(password, aes_salt)
    
    payload_str = json.dumps(dataclasses.asdict(sample_token)).encode('utf-8')
    
    start_time = time.perf_counter()
    for _ in range(iterations):
        encrypt_blob(aes_key, payload_str)
    end_time = time.perf_counter()
    enc_avg_ms = ((end_time - start_time) * 1000) / iterations
    
    cipher_blob = encrypt_blob(aes_key, payload_str)
    
    start_time = time.perf_counter()
    for _ in range(iterations):
        decrypt_blob(aes_key, cipher_blob)
    end_time = time.perf_counter()
    dec_avg_ms = ((end_time - start_time) * 1000) / iterations
    
    results.append(("AES-GCM Local Encryption", f"{enc_avg_ms:.4f} ms"))
    results.append(("AES-GCM Local Decryption", f"{dec_avg_ms:.4f} ms"))
    
    # --- Token Serialized Size ---
    print("[*] Calculating Local File & Request Byte Sizes...")
    token_json_str = json.dumps(dataclasses.asdict(sample_token))
    token_byte_len = len(token_json_str.encode('utf-8'))
    sig_byte_len = len(sample_token.signature.encode('utf-8'))
    
    results.append(("Single Token JSON Payload Length", f"{token_byte_len} bytes"))
    results.append(("ECDSA Signature Length (Hex)", f"{sig_byte_len} bytes"))
    
    # --- Full Transaction Packet Size ---
    tx_package = TransactionPackage(
        transaction_id=str(uuid.uuid4()),
        buyer_id_hash=owner_hash,
        merchant_id="MerchantDummy-abc",
        tokens=[sample_token, generate_token(50), generate_token(10)],
        transaction_timestamp=now,
        requested_amount=160,
        buyer_display_name="Speedy User"
    )
    tx_json_str = json.dumps(dataclasses.asdict(tx_package))
    tx_byte_len = len(tx_json_str.encode('utf-8'))
    results.append(("Offline Transmission Package Size", f"{tx_byte_len} bytes"))
    
    # === Output ===
    output_lines = [
        "",
        "| Metric " + " " * 31 + " | Value (time/size) |",
        "| " + "-" * 38 + " | " + "-" * 17 + " |"
    ]
    for metric, value in results:
        output_lines.append(f"| {metric:<38} | {value:<17} |")
    
    final_output = "\n".join(output_lines)
    print(final_output)

    # Dump file
    bench_dir = os.path.dirname(__file__)
    res_file = os.path.join(bench_dir, "performance_results.txt")
    with open(res_file, "w") as f:
        f.write("--- Offline Token Benchmark Results ---\n")
        f.write(final_output + "\n")
    print("\n[OK] Logs securely committed to file system.")

if __name__ == "__main__":
    run_benchmarks()