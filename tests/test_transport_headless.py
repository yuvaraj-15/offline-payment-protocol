"""
Transport Layer E2E Test (Headless, Pure TCP).

Verifies TCP socket connection, framing, protocol, and data transfer.
Bypasses QR scanning (directly reads ip/port from merchant stdout).
Patches get_lan_ip to return 127.0.0.1 so server binds on loopback.
"""
import subprocess
import sys
import time
import json
import os
import threading
import queue
import unittest.mock

# ---- Patch getpass before importing wallet modules ----
unittest.mock.patch('getpass.getpass', return_value='test_pass_transport').start()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from wallet import core as wallet_core  # type: ignore[import]
from wallet import transport as wallet_transport  # type: ignore[import]
from bank import database as bank_db  # type: ignore[import]
from bank import keys as bank_main  # type: ignore[import]
from merchant import database as merch_db  # type: ignore[import]

def run_test() -> None:
    print("--- HEADLESS TCP TRANSPORT TEST ---")

    # 1. Clean State
    for f in ["merchant/merchant.db", "wallet/wallet.db", "wallet/.salt"]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    bank_db.init_db(reset=True)
    merch_db.init_db(reset=True)

    # 2. Ensure bank key exists
    bank_main.load_or_generate_key()

    # 3. Preload Wallet
    print("\n[Setup] Preloading Wallet...")
    try:
        wallet_core.preload_funds("test_pass_transport", 500)
    except Exception as e:
        print(f"[FAIL] Preload: {e}")
        sys.exit(1)
    print("[Setup] Wallet preloaded OK")

    # 4. Start Merchant Subprocess (headless).
    #    MERCHANT_TEST_LOOPBACK=1 signals merchant/transport.py to return
    #    127.0.0.1 from get_lan_ip(), allowing loopback testing.
    print("\n[Setup] Starting Merchant Server (headless, loopback)...")
    cmd = [sys.executable, "run_merchant.py", "TestMerch", "--headless"]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["MERCHANT_TEST_LOOPBACK"] = "1"  # Triggers loopback IP in server

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        bufsize=1,
    )

    # 5. Read output in background; signal when QR line found
    qr_queue: queue.Queue = queue.Queue()

    def reader() -> None:
        assert proc.stdout is not None
        for raw_line in proc.stdout:  # type: ignore[union-attr]
            line = raw_line.strip()
            print(f"  [Merchant] {line}")
            if "QR Data:" in line and "{" in line:
                try:
                    start = line.find('{')
                    end = line.rfind('}') + 1
                    info = json.loads(line[start:end])  # type: ignore[index]
                    qr_queue.put(info)
                except Exception:
                    pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    try:
        # 6. Wait for QR payload (timeout 10s)
        try:
            merchant_info = qr_queue.get(timeout=10)
        except queue.Empty:
            print("[FAIL] Timeout waiting for merchant QR data")
            sys.exit(1)

        merchant_id: str = merchant_info["merchant_id"]
        ip: str = merchant_info["ip"]
        port: int = int(merchant_info["port"])
        print(f"\n[Test] Merchant: {merchant_id} | {ip}:{port}")

        # 7. Create Payment Packet
        print("[Test] Creating payment packet...")
        try:
            packet_json = wallet_core.create_payment_packet(
                "test_pass_transport", merchant_id, 100
            )
        except Exception as e:
            print(f"[FAIL] Packet creation: {e}")
            sys.exit(1)
        print(f"[Test] Packet created ({len(packet_json)} chars)")

        # 8. Send via Transport
        print(f"[Test] Sending to {ip}:{port} ...")
        success = wallet_transport.send_payment(packet_json, ip, port)

        # Give merchant a moment to log its response
        time.sleep(0.5)

        if success:
            print("\n[PASS] Transport E2E Test PASSED — ACK_SUCCESS received!")
        else:
            print("\n[FAIL] Transport E2E Test FAILED — ACK_REJECT or timeout")
            sys.exit(1)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        print("\n[Cleanup] Merchant stopped.")

if __name__ == "__main__":
    run_test()
