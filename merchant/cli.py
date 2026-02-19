"""Merchant Command Line Interface."""
import argparse
import sys
import json
from merchant import core, database  # type: ignore[import]

def main():
    parser = argparse.ArgumentParser(description="Offline Merchant (Role A)")
    subparsers = parser.add_subparsers(dest="command")
    
    # Init DB
    p_init = subparsers.add_parser("init", help="Initialize Merchant Ledger")
    
    # Receive Payment
    p_receive = subparsers.add_parser("receive", help="Process Offline Payment Packet")
    # Argument for file input, or stdin if not provided
    p_receive.add_argument("--file", "-f", help="Path to JSON packet file", default=None)
    
    # List Transactions
    p_list = subparsers.add_parser("history", help="Show transaction log")

    # Settle
    p_settle = subparsers.add_parser("settle", help="Settled pending transactions")

    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "init":
            database.init_db()
            print("[SUCCESS] Merchant Ledger Initialized.")
            
        elif args.command == "receive":
            packet_str = ""
            if args.file:
                with open(args.file, "r") as f:
                    packet_str = f.read()
            else:
                print("Paste JSON Packet below (Press Ctrl+D or Ctrl+Z to finish):")
                # Read multi-line input
                lines = sys.stdin.readlines()
                packet_str = "".join(lines)
            
            packet_str = packet_str.strip()
            if not packet_str:
                print("[ERROR] Empty input.")
                return

            try:
                success = core.process_payment(packet_str)
                if success:
                    print("[SUCCESS] PAYMENT VERIFIED & ACCEPTED.")
                else:
                    print("[REJECTED] Duplicate Transaction or Token detected.")
            except ValueError as e:
                print(f"[REJECTED] Validation Failed: {e}")
            except Exception as e:
                print(f"[ERROR] Processing Error: {e}")
                
        elif args.command == "history":
            with database.get_db() as conn:
                rows = conn.execute("SELECT * FROM transactions").fetchall()
                print(f"History ({len(rows)}):")
                for r in rows:
                    print(f"- {r['transaction_id'][:8]}... | Amount: {r['total_amount']} | Status: {r['status']}")

        elif args.command == "settle":
            from merchant import settlement
            count = settlement.settle_pending_transactions()
            print(f"[SUCCESS] Settled {count} transactions with Bank.")

    except Exception as e:
        print(f"[UNEXPECTED] {e}")

if __name__ == "__main__":
    main()
