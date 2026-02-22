import time
from wallet import database  # type: ignore[import]
from wallet.core import _get_master_key, get_or_create_identity  # type: ignore[import]
from bank import refund as bank_refund  # type: ignore[import]

def request_refunds(password: str) -> int:
    key = _get_master_key(password)
    buyer_id = get_or_create_identity(password)
    
    tokens = database.list_unspent_tokens(key)
    now = int(time.time())
    
    refund_count: int = 0
    expired_ids = []
    
    for t in tokens:
        if t.expiry_timestamp < now:
            try:
                status = bank_refund.request_refund(buyer_id, t.token_id)
                if status == "REFUNDED":
                    expired_ids.append(t.token_id)
                    refund_count += 1  # type: ignore[operator]
                elif status == "FAILED_SPENT":
                    pass
            except Exception as e:
                print(f"Refund Error {t.token_id}: {e}")
                
    if expired_ids:
         database.mark_tokens_spent(expired_ids)
         
    return refund_count
