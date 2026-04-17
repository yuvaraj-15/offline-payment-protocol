import os
import sys
import logging

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from merchant.database import init_db as m_init 

def reset_merchant():
    print("Resetting Merchant Configuration & Database...")
    
    m_init(reset=True)
    print(" -> Dropped and recreated merchant.db tables")
    
    print("\n--- Merchant Environment Completely Reset ---")
    print("Run `python merchant_app.py` to start fresh.")

if __name__ == "__main__":
    reset_merchant()
