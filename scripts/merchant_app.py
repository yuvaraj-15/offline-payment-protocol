import sys
import sqlite3
import datetime
import logging
import threading
import os
import time

# ---- Bootstrap ----
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Suppress debug logs
logging.getLogger().setLevel(logging.CRITICAL)

from merchant import transport as merch_transport  # type: ignore[import]
from merchant import database as merch_db  # type: ignore[import]
from merchant import settlement as merch_settlement  # type: ignore[import]

_poller_started = False

def print_separator():
    print("-" * 40)

def print_header(title: str):
    print_separator()
    print(title)
    print_separator()

def get_db():
    conn = sqlite3.connect(merch_db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def check_merchant_identity() -> str:
    import uuid
    merchant_id = merch_db.load_config("merchant_id")
    if not merchant_id:
        name = input("Enter Merchant Display Name: ").strip()
        merchant_id = f"Merchant-{uuid.uuid4().hex}"
        merch_db.save_config("merchant_id", merchant_id)
        merch_db.save_config("merchant_display_name", name)
    
    name = merch_db.load_config("merchant_display_name") or "Unknown"
    print_header("Merchant Identity")
    print(f"Merchant Name       : {name}")
    print(f"Merchant Internal ID: {merchant_id}")
    print(f"Listening Port      : 5050")
    print_separator()
    return merchant_id

def poll_new_transactions():
    """Background thread that polls for new transactions and prints the summary."""
    last_tx_set: set[str] = set()
    
    # Initialize seen transactions so we don't print history
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT transaction_id FROM transactions").fetchall()
            last_tx_set = {r["transaction_id"] for r in rows}
    except Exception:
        pass

    while True:
        time.sleep(1.0) # Check every second
        try:
            with get_db() as conn:
                # Fetch all transactions to see if there are new ones
                rows = conn.execute(
                    "SELECT transaction_id, buyer_id_hash, total_amount, timestamp, requested_amount, buyer_display_name "
                    "FROM transactions"
                ).fetchall()
                
                current_tx_set = {str(r["transaction_id"]) for r in rows}
                new_txs = current_tx_set - last_tx_set
                
                if new_txs:
                    for r in rows:
                        tx_id = r["transaction_id"]
                        if tx_id in new_txs:
                            # Found a new transaction. Need to count its tokens.
                            tok_row = conn.execute(
                                "SELECT COUNT(*) FROM received_tokens WHERE transaction_id=?", 
                                (tx_id,)
                            ).fetchone()
                            tok_count = tok_row[0] if tok_row else 0
                            
                            cust_hash = r["buyer_id_hash"][:10]
                            buyer_name = r["buyer_display_name"]
                            amount_recd = r["total_amount"]
                            req_amount = r["requested_amount"]
                            change = amount_recd - req_amount
                            ts = r["timestamp"]
                            dt = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                            
                            print("\n" + "-" * 40)
                            print("Payment Received")
                            print("-" * 40)
                            print(f"Customer Name  : {buyer_name}")
                            print(f"Customer Hash  : {cust_hash}")
                            print(f"Requested Amt  : {req_amount}")
                            print(f"Token Value    : {amount_recd}")
                            print(f"Change Due     : {change}")
                            print(f"Tokens Count   : {tok_count}")
                            print(f"Timestamp      : {dt}")
                            print("Status         : PENDING (Awaiting Settlement)")
                            print("-" * 40)
                            
                    last_tx_set = current_tx_set
        except Exception:
            pass

def menu_start_server(mid: str):
    global _poller_started
    print_header("1. START PAYMENT SERVER")
    print("Starting server... Press 'q' in QR window or Ctrl+C to stop.")
    
    # Start the polling thread only once
    if not _poller_started:
        poller = threading.Thread(target=poll_new_transactions, daemon=True)
        poller.start()
        _poller_started = True
    
    try:
        # Blocks indefinitely under normal circumstances. Use headless=False to show QR.
        merch_transport.start_server(mid, headless=False)
    except KeyboardInterrupt:
        print("\nServer stopped.")
    except Exception as e:
        print(f"Server error: {e}")

def menu_view_pending():
    print_header("Pending Transactions")
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT transaction_id, total_amount, timestamp "
                "FROM transactions WHERE status='PENDING'"
            ).fetchall()
            
        print(f"{'Transaction ID':<14} | {'Amount':<6} | {'Timestamp'}")
        print_separator()
        for r in rows:
            tx = r["transaction_id"][:8]
            amt = str(r["total_amount"])
            dt = datetime.datetime.fromtimestamp(r["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
            print(f"{tx:<14} | {amt:<6} | {dt}")
        print_separator()
    except Exception as e:
        print(f"Error viewing pending: {e}")

def menu_view_settled():
    print_header("Settled Transactions")
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT transaction_id, total_amount, timestamp "
                "FROM transactions WHERE status='SETTLED'"
            ).fetchall()
            
        print(f"{'Transaction ID':<14} | {'Amount':<6} | {'Transaction Time'}")
        print_separator()
        for r in rows:
            tx = r["transaction_id"][:8]
            amt = str(r["total_amount"])
            dt = datetime.datetime.fromtimestamp(r["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
            print(f"{tx:<14} | {amt:<6} | {dt}")
        print_separator()
    except Exception as e:
        print(f"Error viewing settled: {e}")

def menu_settle():
    print_header("4. SETTLE WITH BANK")
    try:
        # Pre-calculate to determine what was successfully credited in this run
        with get_db() as conn:
            pending = conn.execute(
                "SELECT transaction_id, total_amount "
                "FROM transactions WHERE status='PENDING'"
            ).fetchall()
            pending_dict = {r["transaction_id"]: r["total_amount"] for r in pending}

        # Call strictly public settlement logic without stdout redirection
        count = merch_settlement.settle_pending_transactions()

        with get_db() as conn:
            settled = conn.execute(
                "SELECT transaction_id FROM transactions WHERE status='SETTLED'"
            ).fetchall()
            settled_ids = {r["transaction_id"] for r in settled}

        # Compute amount based on delta of status
        credited = sum(pending_dict[tx_id] for tx_id in pending_dict if tx_id in settled_ids)

        print_header("Settlement Summary")
        print(f"Transactions Settled : {count}")
        print(f"Total Credited       : {credited}")
        print_separator()
    except Exception as e:
        print(f"Error settling with bank: {e}")

def run():
    mid = check_merchant_identity()
    while True:
        print_header("Offline Payment Merchant")
        print("1. Start Payment Server")
        print("2. View Pending Transactions")
        print("3. View Settled Transactions")
        print("4. Settle with Bank")
        print("5. Exit")
        print_separator()
        
        choice = input("Select option: ").strip()
        
        if choice == "1":
            menu_start_server(mid)
        elif choice == "2":
            menu_view_pending()
        elif choice == "3":
            menu_view_settled()
        elif choice == "4":
            menu_settle()
        elif choice == "5":
            break
        else:
            print("Invalid option.")

if __name__ == "__main__":
    try:
        merch_db.init_db()
        run()
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"A fatal error occurred: {e}")
        sys.exit(1)
