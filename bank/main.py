"""
Main entry point for Bank Module.
- Initializes Database (with reset for clean runs).
- Generates or loads ECDSA key pair.
- Demonstrates the full token lifecycle.
"""
import os
import sys
import time

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]
from cryptography.hazmat.primitives import serialization  # type: ignore[import]

from bank.database import init_db, create_account, get_balance  # type: ignore[import]
from bank.issuance import issue_tokens  # type: ignore[import]
from bank.settlement import settle_transaction  # type: ignore[import]
from bank.refund import request_refund  # type: ignore[import]
from shared.models import TransactionPackage  # type: ignore[import]
from shared.crypto import derive_owner_hash  # type: ignore[import]

BANK_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(BANK_DIR, "bank_private_key.pem")
PUB_KEY_FILE = os.path.join(BANK_DIR, "public_key.pem")


def load_or_generate_key():
    """Load an existing key from disk, or generate and persist a new one.
    Always exports the public key to public_key.pem."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
    else:
        print("Generating new Bank Key...")
        private_key = ec.generate_private_key(ec.SECP256R1())
        with open(KEY_FILE, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

    # Always export public key
    public_key = private_key.public_key()
    with open(PUB_KEY_FILE, "wb") as f:
        f.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    return private_key


def main():
    print("=" * 60)
    print("  BANK MODULE - Full Lifecycle Demonstration")
    print("=" * 60)

    # Reset DB for a clean demo run
    init_db(reset=True)
    private_key = load_or_generate_key()
    public_key = private_key.public_key()

    # ---- Setup ----
    print("\n--- Setup Users ---")
    create_account("Alice", 1000)
    create_account("MerchantBob", 0)
    print(f"  Alice Balance:       {get_balance('Alice')}")
    print(f"  MerchantBob Balance: {get_balance('MerchantBob')}")

    # ---- 1. Issuance ----
    print("\n--- Phase 1: Issuance (Alice requests Rs.350) ---")
    tokens = issue_tokens(private_key, "Alice", 350)
    for t in tokens:
        print(f"  Token {t.token_id[:8]}... denomination=Rs.{t.denomination}")
    print(f"  Issued {len(tokens)} tokens.")
    print(f"  Alice Balance After: {get_balance('Alice')}")

    # ---- 2. Payment Simulation ----
    print("\n--- Phase 2: Payment Simulation (Alice -> MerchantBob) ---")
    payment_tokens = tokens[:2]  # first two tokens (200 + 100 = Rs.300)
    total_payment = sum(t.denomination for t in payment_tokens)

    tx_package = TransactionPackage(
        transaction_id="tx-101",
        buyer_id_hash=derive_owner_hash("Alice"),
        merchant_id="MerchantBob",
        tokens=payment_tokens,
        transaction_timestamp=int(time.time()),
    )
    print(f"  Payment Package: {len(payment_tokens)} tokens, Rs.{total_payment}")

    # ---- 3. Settlement ----
    print("\n--- Phase 3: Settlement (MerchantBob submits to Bank) ---")
    results = settle_transaction(public_key, tx_package)
    for tid, status in results.items():
        print(f"  {tid[:8]}... -> {status}")
    print(f"  MerchantBob Balance After: {get_balance('MerchantBob')}")

    # ---- 4. Double-Spending Attempt ----
    print("\n--- Phase 4: Double-Spending Attempt (MerchantBob resubmits) ---")
    results_replay = settle_transaction(public_key, tx_package)
    for tid, status in results_replay.items():
        print(f"  {tid[:8]}... -> {status}")

    # ---- 5. Invalid Refund (spent token) ----
    print("\n--- Phase 5: Refund Attempt on SPENT Token ---")
    refund_status = request_refund("Alice", payment_tokens[0].token_id)
    print(f"  Result (expect FAILED_SPENT): {refund_status}")

    # ---- 6. Invalid Refund (not yet expired) ----
    print("\n--- Phase 6: Refund Attempt on ISSUED but NOT-EXPIRED Token ---")
    unused_token = tokens[2]  # the Rs.50 token that was never spent
    refund_status = request_refund("Alice", unused_token.token_id)
    print(f"  Result (expect FAILED_NOT_EXPIRED): {refund_status}")

    # ---- Summary ----
    print("\n" + "=" * 60)
    print("  Final Balances")
    print(f"  Alice:       Rs.{get_balance('Alice')}")
    print(f"  MerchantBob: Rs.{get_balance('MerchantBob')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
