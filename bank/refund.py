import time
from shared.crypto import derive_owner_hash  
from bank.database import get_db_connection  

def request_refund(buyer_id: str, token_id: str) -> str:

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

            if requested_hash != owner_id_hash:
                conn.rollback()
                return "FAILED_OWNER_MISMATCH"

            if status != "ISSUED":
                conn.rollback()
                return f"FAILED_{status}"

            if now <= expires_at:
                conn.rollback()
                return "FAILED_NOT_EXPIRED"

            cursor.execute(
                """
                UPDATE tokens
                SET status = 'REFUNDED', refunded_at = ?
                WHERE token_id = ? AND status = 'ISSUED'
                """,
                (now, token_id),
            )

            if cursor.rowcount != 1:
                conn.rollback()
                return "FAILED_CONCURRENT_MODIFICATION"

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
