import os
import sys
import json
import sqlite3
from datetime import datetime
import getpass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from wallet import core as wallet_core  # type: ignore[import]
from wallet import transport as wallet_transport  # type: ignore[import]

def print_separator():
    print("-" * 40)

def print_header(title: str):
    print_separator()
    print(title)
    print_separator()

from shared.paths import WALLET_SALT_PATH, WALLET_DB_PATH  # type: ignore[import]

def check_wallet_exists() -> bool:
    return WALLET_SALT_PATH.exists() and WALLET_DB_PATH.exists()

def init_wallet():
    print("No wallet found.")
    print("1. Create New Wallet")
    print("2. Exit")
    choice = input("Select option: ").strip()
    if choice == "1":
        pwd = getpass.getpass("Set password: ")
        pwd2 = getpass.getpass("Confirm password: ")
        if pwd != pwd2:
            print("Passwords do not match. Aborting.")
            sys.exit(1)
        name = input("Enter Display Name: ").strip()
        try:
            wallet_core.get_or_create_identity(pwd, display_name=name)
            print("Wallet created successfully.")
        except Exception as e:
            print(f"Failed to create wallet: {str(e)}")
            sys.exit(1)
    else:
        sys.exit(0)

def menu_view_identity():
    print_header("VIEW WALLET IDENTITY")
    pwd = getpass.getpass("Enter password: ")
    try:
        from wallet import crypto as wallet_crypto  # type: ignore[import]
        from wallet import database as wallet_db  # type: ignore[import]
        with open(WALLET_SALT_PATH, "rb") as f:
            salt = f.read()
        key, _ = wallet_crypto.derive_key(pwd, salt)
        
        buyer_id = wallet_db.load_config("buyer_id", key)
        if not buyer_id:
            print("Wallet not initialized or corrupted.")
            return
            
        buyer_name = wallet_db.load_config("buyer_display_name", key) or "Unknown"
        import hashlib
        id_hash = hashlib.sha256(buyer_id.encode('utf-8')).hexdigest()
        
        print(f"Display Name : {buyer_name}")
        print(f"Internal ID  : {buyer_id}")
        print(f"ID Hash      : {id_hash}")
        print_separator()
    except Exception as e:
        print("Invalid password or error.")

def menu_preload():
    print_header("1. PRELOAD FUNDS")
    try:
        amount_str = input("Enter amount: ").strip()
        try:
            amount = int(amount_str)
        except ValueError:
            print("Enter a valid amount.")
            return
        pwd = getpass.getpass("Enter password: ")
        
        try:
            wallet_core.get_or_create_identity(pwd)
        except ValueError:
            print("Invalid password.")
            return

        before_counts = {}
        with sqlite3.connect(WALLET_DB_PATH) as conn:
            rows_before = conn.execute("SELECT denomination FROM tokens WHERE status='UNSPENT'").fetchall()
            for r in rows_before:
                d = r[0]
                before_counts[d] = before_counts.get(d, 0) + 1
            before_balance = sum(r[0] for r in rows_before)

        count = wallet_core.preload_funds(pwd, amount)

        if count == 0:
            print("Enter a valid amount.")
            return

        after_counts = {}
        with sqlite3.connect(WALLET_DB_PATH) as conn:
            rows_after = conn.execute("SELECT denomination FROM tokens WHERE status='UNSPENT'").fetchall()
            for r in rows_after:
                d = r[0]
                after_counts[d] = after_counts.get(d, 0) + 1
            after_balance = sum(r[0] for r in rows_after)
            
        issued = {}
        for d, c in after_counts.items():
            diff = c - before_counts.get(d, 0)
            if diff > 0:
                issued[d] = diff

        print_header("Preload Successful")
        print(f"Amount Loaded : {amount}")
        print("Tokens Issued :")
        for d in sorted(issued.keys(), reverse=True):
            print(f"    {d} x {issued[d]}")
        print(f"New Balance   : {after_balance}")
        print_separator()

    except ValueError as e:
        if "Invalid password" in str(e) or "Incorrect password" in str(e):
            print("Invalid password.")
        else:
            print(f"Error: {e}")
    except Exception as e:
        print(f"Error preloading funds: {e}")

def menu_check_balance():
    print_header("2. CHECK BALANCE")
    try:
        pwd = getpass.getpass("Enter password: ")
        try:
            wallet_core.get_or_create_identity(pwd)
        except ValueError:
            print("Invalid password.")
            return

        try:
            from wallet import database as wallet_db  # type: ignore[import]
            wallet_db.expire_stale_tokens()
        except Exception:
            pass

        with sqlite3.connect(WALLET_DB_PATH) as conn:
            rows_unspent = conn.execute("SELECT denomination FROM tokens WHERE status='UNSPENT'").fetchall()
            unspent_cnt = len(rows_unspent)
            unspent_sum = sum(r[0] for r in rows_unspent)
            
            unspent_counts = {}
            for r in rows_unspent:
                d = r[0]
                unspent_counts[d] = unspent_counts.get(d, 0) + 1
            
            spent_cnt = conn.execute("SELECT COUNT(*) FROM tokens WHERE status='SPENT'").fetchone()[0]
            expired_cnt = conn.execute("SELECT COUNT(*) FROM tokens WHERE status='EXPIRED'").fetchone()[0]

        print_header("Wallet Balance Summary")
        print(f"Total Balance   : {unspent_sum}")
        print(f"Unspent Tokens  : {unspent_cnt}")
        for d in sorted(unspent_counts.keys(), reverse=True):
            print(f"    {d} x {unspent_counts[d]}")
        print(f"Spent Tokens    : {spent_cnt}")
        print(f"Expired Tokens  : {expired_cnt}")
        print_separator()

    except Exception as e:
        print(f"Error checking balance: {e}")

def menu_pay():
    print_header("3. PAY MERCHANT")
    try:
        amount_str = input("Enter amount: ").strip()
        amount = int(amount_str)
        pwd = getpass.getpass("Enter password: ")
        
        try:
            wallet_core.get_or_create_identity(pwd)
        except ValueError:
            print("Invalid password.")
            return
            
        print("Scanning for merchant QR code...")
        try:
            merchant_id, ip, port = wallet_transport.scan_qr()
        except RuntimeError as e:
            print(f"Payment failed.\nReason: {e}")
            return
            
        print_header("Merchant Detected")
        print(f"Merchant ID : {merchant_id}")
        print(f"IP          : {ip}")
        print(f"Port        : {port}")
        print_separator()
        
        
        with sqlite3.connect(WALLET_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT denomination, expiry_ts FROM tokens WHERE status='UNSPENT'").fetchall()
            
        import time
        now = int(time.time())
        valid_denoms = [r["denomination"] for r in rows if r["expiry_ts"] > now + 60]
        valid_denoms.sort(reverse=True)
        
        current_sum = 0
        used_denoms = {}
        for d in valid_denoms:
            if current_sum >= amount: break
            current_sum += d
            used_denoms[d] = used_denoms.get(d, 0) + 1
            
        if current_sum < amount:
            print(f"Payment failed.\nReason: Insufficient funds. Have {current_sum}, need {amount}")
            return
            
        print("Tokens to use:")
        for d in sorted(used_denoms.keys(), reverse=True):
            print(f"    {d} x {used_denoms[d]}")
            
        overpayment = current_sum - amount
        if overpayment > 0:
            print(f"You are overpaying by {overpayment}")
        
        confirm = input("Proceed with payment? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Payment cancelled.")
            return
            
        try:
            packet_json = wallet_core.create_payment_packet(pwd, merchant_id, amount)
        except ValueError as e:
            print(f"Payment failed.\nReason: {e}")
            return
            
        success = wallet_transport.send_payment(packet_json, ip, port)
        
        if success:
            packet_data = json.loads(packet_json)
            tx_id = packet_data.get("transaction_id", "Unknown")
            tokens = packet_data.get("tokens", [])
            total_sent = sum(t.get("denomination", 0) for t in tokens)
            change_due = total_sent - amount
            
            print_header("Payment Successful")
            print(f"Requested Amount    : {amount}")
            print(f"Token Value Sent    : {total_sent}")
            print(f"Physical Change Due : {change_due}")
            print(f"Transaction ID      : {tx_id}")
            print_separator()
            if change_due > 0:
                print(f"WARNING: Merchant must return physical change of {change_due}")
        else:
            print("Payment failed.\nReason: Merchant rejected the transaction or connection timed out.")

    except ValueError as e:
        print(f"Payment failed.\nReason: {e}")
    except Exception as e:
        print(f"Payment failed.\nReason: {e}")

def menu_view_tokens():
    print_header("4. VIEW LOCAL TOKENS")
    try:
        pwd = getpass.getpass("Enter password: ")
        try:
            wallet_core.get_or_create_identity(pwd)
        except ValueError:
            print("Invalid password.")
            return

        try:
            from wallet import database as wallet_db  # type: ignore[import]
            wallet_db.expire_stale_tokens()
        except Exception:
            pass

        tokens_info = wallet_core.get_local_token_details(pwd)

        print_header("Local Tokens")
        print(f"{'Token ID':<10} | {'Amount':<6} | {'Status':<9} | {'Issued':<19} | {'Expiry'}")
        print("-" * 62)
        
        for t in tokens_info:
            short_id = t["token_id"][:8]
            amt = str(t["denomination"])
            status = t["status"]
            issue_dt = datetime.fromtimestamp(t["issue_timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
            exp_dt = datetime.fromtimestamp(t["expiry_timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
            print(f"{short_id:<10} | {amt:<6} | {status:<9} | {issue_dt:<19} | {exp_dt}")
        print("-" * 62)
        
    except Exception as e:
        print(f"Error viewing tokens: {e}")

def run():
    

    if not check_wallet_exists():
        init_wallet()
        
    while True:
        print_header("Offline Payment Wallet")
        print("1. Preload Funds")
        print("2. Check Balance")
        print("3. Pay Merchant")
        print("4. View Local Tokens")
        print("5. View Wallet Identity")
        print("6. Exit")
        print_separator()
        
        choice = input("Select option: ").strip()
        
        if choice == "1":
            menu_preload()
        elif choice == "2":
            menu_check_balance()
        elif choice == "3":
            menu_pay()
        elif choice == "4":
            menu_view_tokens()
        elif choice == "5":
            menu_view_identity()
        elif choice == "6":
            break
        else:
            print("Invalid option.")

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"A fatal error occurred: {e}")
        sys.exit(1)
