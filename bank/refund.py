"""
Refund logic for the Bank module.
Strict enforcement: Refund allowed ONLY if status=ISSUED AND now > expires_at.
State transition: ISSUED -> REFUNDED (atomic, no reverse).
"""
import time
from shared.crypto import derive_owner_hash  # type: ignore[import]
from bank.database import get_db_connection  # type: ignore[import]


def request_refund(buyer_id: str, token_id: str) -> str:
    """
    Authenticated refund request.

    Steps:
      1. Verify buyer_id hash matches the token's owner_id_hash.
      2. Verify token status is ISSUED.
      3. Verify token has expired (now > expires_at).
      4. Atomically transition ISSUED -> REFUNDED.
      5. Credit buyer account.

    Returns a status string indicating the outcome.
    """
    now = int(time.time())
    requested_hash = derive_owner_hash(buyer_id)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        conn.execute("BEGIN IMMEDIATE")

        try:
            cursor.execute(
                "SELECT status, expires_at, denomination, owner_id_hash "
                "FROM tokens WHERE token_id = ?",
                (token_id,),
            )
            row = cursor.fetchone()

            if not row:
                conn.rollback()
                return "FAILED_UNKNOWN"

            status, expires_at, denomination, owner_id_hash = row

            # Verify Ownership
            if requested_hash != owner_id_hash:
                conn.rollback()
                return "FAILED_OWNER_MISMATCH"

            # Check current status
            if status != "ISSUED":
                conn.rollback()
                return f"FAILED_{status}"

            # Enforce expiry rule: refund only AFTER expiry
            if now <= expires_at:
                conn.rollback()
                return "FAILED_NOT_EXPIRED"

            # Atomic transition: ISSUED -> REFUNDED
            cursor.execute(
                """
                UPDATE tokens
                SET status = 'REFUNDED', refunded_at = ?
                WHERE token_id = ? AND status = 'ISSUED'
                """,
                (now, token_id),
            )

            if cursor.rowcount != 1:
                # Another operation beat us (concurrent settlement)
                conn.rollback()
                return "FAILED_CONCURRENT_MODIFICATION"

            # Credit Buyer account
            cursor.execute(
                "SELECT balance FROM accounts WHERE user_id = ?", (buyer_id,)
            )
            acct_row = cursor.fetchone()
            if acct_row:
                new_bal = acct_row[0] + denomination
                cursor.execute(
                    "UPDATE accounts SET balance = ? WHERE user_id = ?",
                    (new_bal, buyer_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO accounts (user_id, balance) VALUES (?, ?)",
                    (buyer_id, denomination),
                )

            conn.commit()
            return "REFUNDED"

        except Exception as e:
            conn.rollback()
            return f"ERROR: {e}"
