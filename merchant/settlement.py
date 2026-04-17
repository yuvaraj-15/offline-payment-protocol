import time
from merchant import database  
from shared.models import TransactionPackage, Token  
from shared.crypto import derive_owner_hash  
from bank import settlement as bank_settlement  
from bank import http_client as bank_client  
from merchant.core import _load_bank_public_key  
import dataclasses

def settle_pending_transactions() -> int:
    
    bank_pub = _load_bank_public_key() 
    
    settled_count: int = 0
    with database.get_db() as conn:
        txs = conn.execute("SELECT * FROM transactions WHERE status = 'PENDING'").fetchall()
        
        for tx in txs:
            tx_id = tx["transaction_id"]
            
            tok_rows = conn.execute("SELECT token_json FROM received_tokens WHERE transaction_id = ?", (tx_id,)).fetchall()
            
            tokens = []
            import json
            for tr in tok_rows:
                t_dict = json.loads(tr["token_json"])
                tokens.append(Token(**t_dict))
                
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
                tx_dict = dataclasses.asdict(pkg)

                response = bank_client.settle_transaction(tx_dict)

                if isinstance(response, dict) and "results" in response:
                    results = response["results"]
                else:
                    results = response

                any_settled = False
                all_settled = True

                for token in pkg.tokens:

                    status = results.get(token.token_id)

                    if status == "SETTLED":

                        conn.execute(
                            "UPDATE received_tokens SET status = 'SETTLED' WHERE transaction_id = ? AND token_json LIKE ?",
                            (tx_id, f"%{token.token_id}%"),
                        )

                        any_settled = True

                    else:
                        all_settled = False

                any_settled = False
                all_settled = True
                for token in pkg.tokens:
                    status = results.get(token.token_id)
                    if status == "SETTLED":
                        conn.execute(
                            "UPDATE received_tokens SET status = 'SETTLED' WHERE transaction_id = ? AND token_json LIKE ?",
                            (tx_id, f"%{token.token_id}%"),
                        )
                        any_settled = True
                    else:
                        all_settled = False

                if all_settled and any_settled:
                    conn.execute("UPDATE transactions SET status = 'SETTLED' WHERE transaction_id = ?", (tx_id,))
                    settled_count += 1  
                elif any_settled:
                    print(f"Partial settlement for {tx_id}: results={results}")
                else:
                    print(f"Settlement rejected for {tx_id}: results={results}")

            except Exception as e:
                print(f"Settlement Failed for {tx_id}: {e}")
                
        conn.commit()
        return settled_count
