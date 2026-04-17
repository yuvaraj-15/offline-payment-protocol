import os
import sys
import logging

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from wallet.database import init_db as w_init  
from bank.database import init_db as b_init  

def reset_wallet():
    print("Resetting Wallet Identity & Database...")
    from shared.paths import WALLET_SALT_PATH  
    if WALLET_SALT_PATH.exists():
        os.remove(WALLET_SALT_PATH)
        print(" -> Deleted wallet/.salt")
    else:
        print(" -> No wallet/.salt found.")
    
    w_init(reset=True)
    print(" -> Deleted and recreated wallet.db tables")
    
    print("\nResetting simulated Bank Database (to allow fresh preloads)...")
    b_init(reset=True)
    print(" -> Deleted and recreated bank.db tables")
    
    print("\n--- Wallet Environment Completely Reset ---")
    print("Run `python wallet_app.py` to start fresh.")

if __name__ == "__main__":
    reset_wallet()
