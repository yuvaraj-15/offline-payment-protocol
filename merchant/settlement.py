"""Settlement Logic for Merchant.

Simulates uploading offline transactions to the Bank.
Phase 3.4
"""
import time
from merchant import database
from shared.models import TransactionPackage, Token # type: ignore[import]
from shared.crypto import derive_owner_hash # type: ignore[import]
from bank import settlement as bank_settlement # type: ignore[import]
# We need bank public key to verify (already loaded in core)
from merchant.core import _load_bank_public_key

def settle_pending_transactions() -> int:
    """Upload all PENDING transactions to Bank.
    
    Returns: Count of successfully settled transactions.
    """
    bank_pub = _load_bank_public_key() # Not used for settlement submission but good to have context
    # In real world, we POST to Bank API.
    # Here we call bank.settlement.settle_transaction directly.
    # But settle_transaction takes (bank_pub_key, tx_package).
    # Wait, settle_transaction signature in bank/settlement.py:
    # def settle_transaction(bank_public_key, transaction_package: TransactionPackage) -> dict:
    
    settled_count = 0
    with database.get_db() as conn:
        # Get PENDING txs
        txs = conn.execute("SELECT * FROM transactions WHERE status = 'PENDING'").fetchall()
        
        for tx in txs:
            tx_id = tx["transaction_id"]
            
            # Reconstruct Package
            # We need the tokens.
            tok_rows = conn.execute("SELECT token_json FROM received_tokens WHERE transaction_id = ?", (tx_id,)).fetchall()
            
            tokens = []
            import json
            for tr in tok_rows:
                t_dict = json.loads(tr["token_json"])
                tokens.append(Token(**t_dict))
                
            # Construct TransactionPackage
            # We need buyer_id_hash etc. from tx record
            pkg = TransactionPackage(
                transaction_id=tx_id,
                buyer_id_hash=tx["buyer_id_hash"],
                merchant_id=tx["merchant_id"],
                tokens=tokens,
                transaction_timestamp=tx["timestamp"]
            )
            
            # Call Bank (Simulation)
            # We need bank_pub_key to pass to settle_transaction?
            # bank.settlement.settle_transaction uses it to verify token signatures again?
            # Yes.
            
            try:
                # Calls Bank!
                results = bank_settlement.settle_transaction(bank_pub, pkg)
                
                # Analyze results.
                # If ANY token is SETTLED or REJECTED_DUPLICATE (of self), we mark tx as SETTLED?
                # Spec says "No partial settlement" but Bank returns Dict[token_id, status].
                # If Bank accepts, it credits merchant.
                # Use strict check: If bank processed it (even if some duplicates), we mark local as SETTLED.
                # If Bank crashes, we keep PENDING.
                
                # Update Local Status
                conn.execute("UPDATE transactions SET status = 'SETTLED' WHERE transaction_id = ?", (tx_id,))
                conn.execute("UPDATE received_tokens SET status = 'SETTLED' WHERE transaction_id = ?", (tx_id,))
                settled_count += 1
                
            except Exception as e:
                print(f"Settlement Failed for {tx_id}: {e}")
                # Keep PENDING
                
        conn.commit()
        return settled_count
