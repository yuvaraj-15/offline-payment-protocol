"""Refund Logic for Wallet.

Simulates requesting refunds for expired tokens.
Phase 3.4
"""
import time
from wallet import database
from wallet.core import _get_master_key, get_or_create_identity
from bank import refund as bank_refund # type: ignore[import]

def request_refunds(password: str) -> int:
    """Find expired/unspent tokens and request refund from Bank.
    
    Returns: Count of refunded tokens.
    """
    key = _get_master_key(password)
    buyer_id = get_or_create_identity(password)
    
    # 1. Identify Tokens (Local)
    # UNSPENT or SPENT?
    # Spec: "If token expires unused... Buyer may submit refund request."
    # If marked SPENT locally but transfer failed? They are lost to user unless we allow refund of SPENT?
    # Spec says: "A token may transition only once from ISSUED -> SPENT or ISSUED -> REFUNDED."
    # Local wallet has UNSPENT and SPENT.
    # If SPENT locally, we assume they reached Merchant.
    # If they didn't, and expired, can we refund?
    # Bank will check if they are SPENT in Ledger.
    # If Bank says "ISSUED" (not spent), we can refund.
    # So we should try to refund even SPENT tokens if they are expired?
    # Dangerous. User might double-dip if merchant settles late.
    # But Merchant checks expiry. Merchant won't accept expired tokens.
    # So if token is EXPIRED and still ISSUED at Bank, it means Merchant never settled it.
    # Thus safe to refund.
    
    # We will try to refund ALL Expired tokens (UNSPENT + SPENT) that are simulated "stuck".
    # But `database.list_unspent_tokens` only returns UNSPENT.
    # We should query all?
    # For MVP, let's stick to UNSPENT tokens that expired.
    
    # Get all UNSPENT
    tokens = database.list_unspent_tokens(key)
    now = int(time.time())
    
    refund_count = 0
    expired_ids = []
    
    for t in tokens:
        if t.expiry_timestamp < now:
            # It's expired. Try refund.
            try:
                status = bank_refund.request_refund(buyer_id, t.token_id)
                if status == "REFUNDED":
                    expired_ids.append(t.token_id)
                    refund_count += 1
                elif status == "FAILED_SPENT":
                    # Mark as SPENT locally if not already
                    pass
            except Exception as e:
                print(f"Refund Error {t.token_id}: {e}")
                
    # Update Local Status to REFUNDED (or EXPIRED -> REFUNDED)
    # Our DB has 'EXPIRED' status?
    # We just use 'SPENT' or 'REFUNDED'?
    # Wallet DB schema has 'UNSPENT', 'SPENT', 'EXPIRED'.
    # We should add 'REFUNDED' to schema or just use 'EXPIRED'?
    # Schema check constraint: `CHECK(status IN ('UNSPENT', 'SPENT', 'EXPIRED'))`
    # We need to migrate schema or just verify `implementation_plan` said:
    # "status: TEXT ('UNSPENT', 'SPENT', 'EXPIRED')"
    # Wait, if I refund, it's effectively final.
    # I'll update them to 'EXPIRED' (which basically means dead) or 'SPENT'.
    # Let's map REFUNDED to 'EXPIRED' in local DB for now, as it removes them from UNSPENT.
    # Or 'SPENT'.
    # Actually, `mark_tokens_spent` sets them to SPENT.
    # I'll create `mark_tokens_refunded` or just reuse `mark_tokens_spent`?
    # Better to differentiate.
    # But strict schema constraint might block 'REFUNDED'.
    # I'll use `mark_tokens_spent` to remove them from available list.
    
    if expired_ids:
         database.mark_tokens_spent(expired_ids)
         
    return refund_count
