"""
Role B - Wallet Runner.

Scans Merchant QR, connects via TCP, sends payment.
Usage: python run_wallet.py <amount>
"""
import sys
import os
import getpass

# Ensure project root in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from wallet import transport, core  # type: ignore[import]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_wallet.py <amount>")
        sys.exit(1)

    amount = int(sys.argv[1])

    print("--- Wallet Payment (TCP) ---")
    password = getpass.getpass("Enter Wallet Password: ")

    try:
        # 0. Validate Password First
        print("Verifying password...")
        try:
            core.get_balance_info(password)
        except Exception:
            print("[ERROR] Invalid password.")
            sys.exit(1)

        # 1. Scan QR
        print("\n[Action] Opening camera — point at Merchant QR code (press 'q' to cancel)")
        mid, ip, port = transport.scan_qr()
        print(f"\n[Scanned] Merchant: {mid} | IP: {ip} | Port: {port}")

        # 2. Confirm
        confirm = input(f"Pay {amount} to {mid}? (y/n): ")
        if confirm.lower() != 'y':
            print("Cancelled.")
            sys.exit(0)

        # 3. Create Packet
        print("Generating payment packet...")
        packet_json = core.create_payment_packet(password, mid, amount)

        # 4. Send
        print(f"Connecting to {ip}:{port} ...")
        success = transport.send_payment(packet_json, ip, port)

        if success:
            print("\n[SUCCESS] Payment accepted by Merchant!")
        else:
            print("\n[FAILURE] Payment rejected or timed out.")
            sys.exit(1)

    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
