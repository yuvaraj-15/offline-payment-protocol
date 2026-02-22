"""
Centralized Architecture Path Resolver
Ensures all script modules resolve file directories securely from the absolute project root.
"""
from pathlib import Path

# Compute absolute path to offline-payment-protocol/
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Dynamic Directories
WALLET_DIR = PROJECT_ROOT / "wallet"
MERCHANT_DIR = PROJECT_ROOT / "merchant"
BANK_DIR = PROJECT_ROOT / "bank"

# File Constants
WALLET_DB_PATH = WALLET_DIR / "wallet.db"
WALLET_SALT_PATH = WALLET_DIR / ".salt"

MERCHANT_DB_PATH = MERCHANT_DIR / "merchant.db"

BANK_DB_PATH = BANK_DIR / "ledger.db"
BANK_KEY_PATH = BANK_DIR / "bank_private_key.pem"
BANK_PUB_KEY_PATH = BANK_DIR / "public_key.pem"
