import subprocess
import sys
import time
import json
import os
import threading
import queue
import unittest.mock


unittest.mock.patch('getpass.getpass', return_value='test_pass_transport').start()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from wallet import core as wallet_core  
from wallet import transport as wallet_transport  
from bank import database as bank_db  
from bank import keys as bank_main  
from merchant import database as merch_db  

def run_test() -> None:
    print("--- HEADLESS TCP TRANSPORT TEST ---")

    for f in ["merchant/merchant.db", "wallet/wallet.db", "wallet/.salt"]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    bank_db.init_db(reset=True)
    merch_db.init_db(reset=True)


    bank_main.load_or_generate_key()


    print("\n[Setup] Preloading Wallet...")
    try:
        wallet_core.preload_funds("test_pass_transport", 500)
    except Exception as e:
        print(f"[FAIL] Preload: {e}")
        sys.exit(1)
    print("[Setup] Wallet preloaded OK")

    print("\n[Setup] Starting Merchant Server (headless, loopback)...")
    cmd = [sys.executable, "run_merchant.py", "TestMerch", "--headless"]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["MERCHANT_TEST_LOOPBACK"] = "1"  

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        bufsize=1,
    )


    qr_queue: queue.Queue = queue.Queue()

    def reader() -> None:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.strip()
            print(f"  [Merchant] {line}")
            if "QR Data:" in line and "{" in line:
                try:
                    start = line.find('{')
                    end = line.rfind('}') + 1
                    info = json.loads(line[start:end])  
                    qr_queue.put(info)
                except Exception:
                    pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    try:
        try:
            merchant_info = qr_queue.get(timeout=10)
        except queue.Empty:
            print("[FAIL] Timeout waiting for merchant QR data")
            sys.exit(1)

        merchant_id: str = merchant_info["merchant_id"]
        ip: str = merchant_info["ip"]
        port: int = int(merchant_info["port"])
        print(f"\n[Test] Merchant: {merchant_id} | {ip}:{port}")


        print("[Test] Creating payment packet...")
        try:
            packet_json = wallet_core.create_payment_packet(
                "test_pass_transport", merchant_id, 100
            )
        except Exception as e:
            print(f"[FAIL] Packet creation: {e}")
            sys.exit(1)
        print(f"[Test] Packet created ({len(packet_json)} chars)")


        print(f"[Test] Sending to {ip}:{port} ...")
        success = wallet_transport.send_payment(packet_json, ip, port)


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
