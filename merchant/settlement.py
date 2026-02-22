import time
from merchant import database  # type: ignore[import]
from shared.models import TransactionPackage, Token  # type: ignore[import]
from shared.crypto import derive_owner_hash  # type: ignore[import]
from bank import settlement as bank_settlement  # type: ignore[import]
from merchant.core import _load_bank_public_key  # type: ignore[import]

def settle_pending_transactions() -> int:
    
    bank_pub = _load_bank_public_key() 
    
    settled_count: int = 0
    with database.get_db() as conn:
        txs = conn.execute("SELECT * FROM transactions WHERE status = 'PENDING'").fetchall()
        
        for tx in txs:
            tx_id = tx["transaction_id"]
            
            # Reconstruct Package
            tok_rows = conn.execute("SELECT token_json FROM received_tokens WHERE transaction_id = ?", (tx_id,)).fetchall()
            
            tokens = []
            import json
            for tr in tok_rows:
                t_dict = json.loads(tr["token_json"])
                tokens.append(Token(**t_dict))
                
            # Construct TransactionPackage
            pkg = TransactionPackage(
                transaction_id=tx_id,
                buyer_id_hash=tx["buyer_id_hash"],
                merchant_id=tx["merchant_id"],
                tokens=tokens,
                transaction_timestamp=tx["timestamp"],
                requested_amount=tx["requested_amount"],
                buyer_display_name=tx["buyer_display_name"] or "Unknown Customer"
            )
            
            try:
                results = bank_settlement.settle_transaction(bank_pub, pkg)
                
                conn.execute("UPDATE transactions SET status = 'SETTLED' WHERE transaction_id = ?", (tx_id,))
                conn.execute("UPDATE received_tokens SET status = 'SETTLED' WHERE transaction_id = ?", (tx_id,))
                settled_count += 1  # type: ignore[operator]
                
            except Exception as e:
                print(f"Settlement Failed for {tx_id}: {e}")
                
        conn.commit()
        return settled_count
