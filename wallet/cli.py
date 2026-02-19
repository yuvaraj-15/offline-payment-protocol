"""Wallet Command Line Interface."""
import argparse
import sys
import getpass
from wallet import core  # type: ignore[import]

def main():
    parser = argparse.ArgumentParser(description="Offline Wallet (Role A)")
    subparsers = parser.add_subparsers(dest="command")
    
    # Preload
    p_load = subparsers.add_parser("preload", help="Load funds from Bank")
    p_load.add_argument("amount", type=int, help="Amount to withdraw")
    
    # Balance
    p_bal = subparsers.add_parser("balance", help="Check local balance")
    
    # Pay
    p_pay = subparsers.add_parser("pay", help="Generate Payment Packet")
    p_pay.add_argument("merchant_id", type=str, help="Merchant ID")
    p_pay.add_argument("amount", type=int, help="Amount to pay")

    # Refund
    p_refund = subparsers.add_parser("refund", help="Request Refund for expired tokens")

    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return

    password = getpass.getpass("Wallet Password: ")
    
    try:
        if args.command == "preload":
            count = core.preload_funds(password, args.amount)
            print(f"[SUCCESS] Successfully loaded {count} tokens.")
            
        elif args.command == "balance":
            info = core.get_balance_info(password)
            print(f"[BALANCE] Total: {info['total']} ({info['count']} tokens)")
            print("Tokens:", [t.token_id[:8]+"..." for t in info['tokens']])
            
        elif args.command == "pay":
            packet = core.create_payment_packet(password, args.merchant_id, args.amount)
            print("\n[PAYMENT PACKET] (Share with Merchant)\n")
            print(packet)
            
        elif args.command == "refund":
            from wallet import refund
            count = refund.request_refunds(password)
            print(f"[SUCCESS] Refund request sent for {count} expired tokens.")

    except ValueError as e:
        print(f"[ERROR] {e}")
    except RuntimeError as e:
        print(f"[CRITICAL] {e}")
    except Exception as e:
        print(f"[UNEXPECTED] {e}")

if __name__ == "__main__":
    main()
