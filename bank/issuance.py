"""
Issuance logic for the Bank module.
"""
import uuid
import time
import sqlite3
from typing import List

from shared.models import Token  # type: ignore[import]
from shared.constants import ISSUER_ID, ALLOWED_DENOMINATIONS, EXPIRY_SECONDS  # type: ignore[import]
from shared.crypto import sign_data, canonical_hash, derive_owner_hash  # type: ignore[import]
from bank.database import get_db_connection  # type: ignore[import]

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]


def issue_tokens(
    private_key: "ec.EllipticCurvePrivateKey", buyer_id: str, amount: int
) -> "List[Token]":
    """
    Issue tokens to a buyer.
    1. Validate amount is positive and a multiple of 10.
    2. Atomic Transaction:
       - Check balance.
       - Deduct amount.
       - Create tokens.
       - Insert tokens to DB.
    Returns list of signed Token objects.
    """
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    if amount % 10 != 0:
        raise ValueError("Amount must be a multiple of 10.")

    owner_hash = derive_owner_hash(buyer_id)

    # Greedy denomination breakdown (largest first)
    remaining = amount
    denominations: List[int] = sorted(ALLOWED_DENOMINATIONS, reverse=True)

    token_denoms: List[int] = []
    for d in denominations:
        while remaining >= d:  # type: ignore[operator]
            token_denoms.append(d)
            remaining -= d  # type: ignore[operator]

    if remaining != 0:
        raise ValueError("Cannot satisfy amount with available denominations.")

    now = int(time.time())
    expiry = now + EXPIRY_SECONDS

    # Build and sign tokens
    generated_tokens: List[Token] = []

    for d in token_denoms:
        tid = str(uuid.uuid4())
        t = Token(
            token_id=tid,
            issuer_id=ISSUER_ID,
            owner_id_hash=owner_hash,
            denomination=d,
            issue_timestamp=now,
            expiry_timestamp=expiry,
            signature="",  # placeholder; hash excludes signature field
        )

        # canonical_hash excludes the signature field per MASTER_SPEC Section 6
        sig = sign_data(private_key, canonical_hash(t))
        t.signature = sig

        generated_tokens.append(t)

    # Atomic DB Transaction
    with get_db_connection() as conn:
        cursor = conn.cursor()
        conn.execute("BEGIN IMMEDIATE")

        try:
            # Check Balance
            cursor.execute(
                "SELECT balance FROM accounts WHERE user_id = ?", (buyer_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"User '{buyer_id}' not found.")
            current_balance = row[0]

            if current_balance < amount:
                raise ValueError(
                    f"Insufficient funds. Have {current_balance}, need {amount}."
                )

            # Deduct Balance
            new_balance = current_balance - amount
            cursor.execute(
                "UPDATE accounts SET balance = ? WHERE user_id = ?",
                (new_balance, buyer_id),
            )

            # Insert Tokens
            for t in generated_tokens:
                cursor.execute(
                    """
                    INSERT INTO tokens
                        (token_id, owner_id_hash, denomination, issuer_id,
                         status, created_at, expires_at)
                    VALUES (?, ?, ?, ?, 'ISSUED', ?, ?)
                    """,
                    (
                        t.token_id,
                        t.owner_id_hash,
                        t.denomination,
                        t.issuer_id,
                        t.issue_timestamp,
                        t.expiry_timestamp,
                    ),
                )

            conn.commit()
            return generated_tokens

        except sqlite3.Error:
            conn.rollback()
            raise
