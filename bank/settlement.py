import time
from typing import Dict

from shared.models import TransactionPackage  # type: ignore[import]
from shared.crypto import verify_signature, canonical_hash  # type: ignore[import]
from bank.database import get_db_connection  # type: ignore[import]

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]

def settle_transaction(
    bank_public_key: "ec.EllipticCurvePublicKey",
    transaction: "TransactionPackage",
) -> "Dict[str, str]":
    
    results: Dict[str, str] = {}
    merchant_id = transaction.merchant_id
    now = int(time.time())

    with get_db_connection() as conn:
        cursor = conn.cursor()

        for token in transaction.tokens:
            try:

                c_hash = canonical_hash(token)
                if not verify_signature(bank_public_key, c_hash, token.signature):
                    results[token.token_id] = "REJECTED_INVALID_SIG"
                    continue

                
                conn.execute("BEGIN IMMEDIATE")

                cursor.execute(
                    """
                    UPDATE tokens
                    SET status = 'SPENT', spent_at = ?, merchant_id = ?
                    WHERE token_id = ? AND status = 'ISSUED'
                    """,
                    (now, merchant_id, token.token_id),
                )

                if cursor.rowcount == 1:
                    cursor.execute(
                        "SELECT balance FROM accounts WHERE user_id = ?",
                        (merchant_id,),
                    )
                    m_row = cursor.fetchone()
                    if m_row:
                        new_bal = m_row[0] + token.denomination
                        cursor.execute(
                            "UPDATE accounts SET balance = ? WHERE user_id = ?",
                            (new_bal, merchant_id),
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO accounts (user_id, balance) VALUES (?, ?)",
                            (merchant_id, token.denomination),
                        )

                    conn.commit()
                    results[token.token_id] = "SETTLED"

                else:
                    conn.rollback()

                    cursor.execute(
                        "SELECT status FROM tokens WHERE token_id = ?",
                        (token.token_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        results[token.token_id] = "REJECTED_UNKNOWN"
                    elif row[0] == "SPENT":
                        results[token.token_id] = "REJECTED_DUPLICATE"
                    elif row[0] == "REFUNDED":
                        results[token.token_id] = "REJECTED_REFUNDED"
                    else:
                        results[token.token_id] = "REJECTED_UNKNOWN_STATE"

            except Exception as e:
                print(f"Error settling token {token.token_id}: {e}")
                if conn.in_transaction:
                    conn.rollback()
                results[token.token_id] = "ERROR"

    return results
