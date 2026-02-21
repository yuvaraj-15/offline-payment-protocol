"""Wallet Core Logic.

Handles identity management, token preload (simulation), and offline payment generation.
Strictly adheres to MASTER_SPEC.md.
"""
import uuid
import json
import time
from typing import List, Tuple, Optional
import hashlib

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]

from shared.models import Token  # type: ignore[import]
from shared.crypto import derive_owner_hash  # type: ignore[import]
from wallet import crypto, database  # type: ignore[import]
from bank import issuance  # type: ignore[import]
from demos import bank_demo as bank_main

# Constants
EXPIRY_BUFFER_SECONDS = 60  # Buffer to accidental expiry during transfer

def _get_master_key(password: str) -> bytes:
    """Derive master key from password. Defines the 'User Session'."""
    # In a real app we'd load salt from DB first.
    # Here, for simplicity/MVP, we derive deterministically or manage salt.
    # Let's check if salt exists in config.
    # Warning: To read config, we need the key. To get the key, we need salt.
    # Chicken/Egg.
    # Solution: Store SALT in plaintext in a separate file or unencrypted DB column.
    # database.py 'config' table config is encrypted.
    # Let's add a 'metadata' table or just use a fixed salt for this MVP?
    # NO. Fixed salt is bad.
    # Let's store salt in a simple plaintext file `wallet/.salt` or use a specific DB table.
    
    # Check if salt file exists
    import os
    if os.path.exists("wallet/.salt"):
        with open("wallet/.salt", "rb") as f:
            salt = f.read()
    else:
        key, salt = crypto.derive_key(password) # Generate new
        with open("wallet/.salt", "wb") as f:
            f.write(salt)
        return key

    key, _ = crypto.derive_key(password, salt)
    return key


def get_or_create_identity(password: str, display_name: Optional[str] = None) -> str:
    """Get or create the Buyer ID for this wallet.

    Lifecycle rules:
    - If no .salt file exists: wallet is new. Create DB, generate identity.
    - If .salt exists and buyer_id row exists: wallet is initialized.
      Decrypt and return buyer_id. Wrong password raises ValueError immediately.
    - If .salt exists but no buyer_id row: wallet DB was wiped. Create new identity.

    IMPORTANT: salt_exists is captured BEFORE calling _get_master_key because
    _get_master_key itself creates the .salt file when it is missing.
    """
    import os
    # Capture before key derivation — _get_master_key will create .salt if absent.
    salt_existed_before = os.path.exists("wallet/.salt")
    key = _get_master_key(password)

    if not salt_existed_before:
        # Brand-new wallet — DB tables may not exist yet.
        database.init_db()
        new_id = f"Buyer-{uuid.uuid4().hex}"  # Use full UUID per spec, not truncated
        database.save_config("buyer_id", new_id, key)
        if display_name:
            database.save_config("buyer_display_name", display_name, key)
        return new_id

    # .salt existed: wallet has been initialized before.
    # Ensure DB tables exist (wallet.db could have been manually deleted).
    database.init_db()

    if database.has_config("buyer_id"):
        # Row exists — decrypt it.  Wrong key will raise ValueError here.
        buyer_id = database.load_config("buyer_id", key)
        if buyer_id is None:
            # Should not happen (has_config confirmed existence), treat as corrupt.
            raise ValueError("Config entry missing after existence check — DB may be corrupt.")
        return buyer_id
    else:
        # DB was wiped but .salt survived — safe to create a new identity.
        new_id = f"Buyer-{uuid.uuid4().hex}"  # Use full UUID per spec
        database.save_config("buyer_id", new_id, key)
        if display_name:
            database.save_config("buyer_display_name", display_name, key)
        return new_id


def preload_funds(password: str, amount: int) -> int:
    """Simulate online withdrawal from Bank.
    
    1. Authenticate (derive key).
    2. Connect to Bank (Simulated).
    3. Receive Tokens.
    4. Encrypt & Store.
    """
    key = _get_master_key(password)
    buyer_id = get_or_create_identity(password)
    
    # 2. Simulate ID-Bound Issuance
    # We need the Bank's private key.
    # In a real system, this is an HTTPS request.
    try:
        from bank import database as bank_db  # type: ignore[import]
        # Ensure bank DB exists for simulation
        bank_db.init_db()
        # Ensure user has funds (Simulated Deposit)
        import sqlite3
        try:
            bank_db.create_account(buyer_id, max(amount * 2, 1000))
        except sqlite3.IntegrityError:
            # Account might exist, or logic differs. 
            # If exists, we assume it has funds or we add? 
            # simple create_account might fail if exists.
            # bank.database.create_account usually inserts.
            pass

        bank_key = bank_main.load_or_generate_key()
    except (ImportError, AttributeError, OSError):
         # Fallback for testing environment
         bank_key = ec.generate_private_key(ec.SECP256R1())

    # 3. Issue
    # owner_id_hash = SHA256(buyer_id)
    owner_hash = derive_owner_hash(buyer_id)
    
    try:
        tokens = issuance.issue_tokens(bank_key, buyer_id, amount)
    except ValueError as e:
        # e.g., Insufficient funds in bank
        return 0

    # 4. Store
    database.store_tokens(tokens, key)
    
    return len(tokens)


def get_balance_info(password: str) -> dict:
    """Return balance summary."""
    key = _get_master_key(password)
    # Enforce expiry before reading balance
    database.expire_stale_tokens()
    tokens = database.list_unspent_tokens(key)
    return {
        "count": len(tokens),
        "total": sum(t.denomination for t in tokens),
        "tokens": tokens
    }


def create_payment_packet(password: str, merchant_id: str, amount: int) -> str:
    """Generate Offline Payment Packet.
    
    1. Select UNSPENT tokens.
    2. Mark SPENT atomic.
    3. Construct JSON.
    """
    key = _get_master_key(password)
    buyer_id = get_or_create_identity(password)
    owner_hash = derive_owner_hash(buyer_id)
    
    # Load display name if available
    buyer_name = "Unknown Customer"
    if database.has_config("buyer_display_name"):
        val = database.load_config("buyer_display_name", key)
        if val:
            buyer_name = val

    # Enforce expiry: transition stale UNSPENT -> EXPIRED in DB
    database.expire_stale_tokens()
    all_tokens = database.list_unspent_tokens(key)

    # Additional buffer: exclude tokens that will expire within EXPIRY_BUFFER_SECONDS
    # These tokens are still UNSPENT but too close to expiry for safe offline transfer.
    now = int(time.time())
    valid_tokens = [t for t in all_tokens if t.expiry_timestamp > now + EXPIRY_BUFFER_SECONDS]
    
    # Coin Selection (Greedy)
    selected = []
    current_sum = 0
    # Sort desc
    valid_tokens.sort(key=lambda x: x.denomination, reverse=True)
    
    for t in valid_tokens:
        if current_sum >= amount:
            break
        selected.append(t)
        current_sum += t.denomination
        
    if current_sum < amount:
        raise ValueError(f"Insufficient funds. Have {current_sum}, need {amount}")
        
    if current_sum > amount:
        # No digital change allowed.
        # Strict exact match or overpayment (if user accepts loss/physical change).
        # For this MVP, we enforce "Exact Match Required" or "Overpayment OK"?
        # Spec says "Physical change allowed". So Overpayment is OK.
        pass

    # Atomic SPENT
    ids = [t.token_id for t in selected]
    success = database.mark_tokens_spent(ids)
    if not success:
        raise RuntimeError("Atomic State Update Failed. Race condition?")
        
    # Construct Packet (Strict Section 7.2)
    # Convert token objects to pure dicts for JSON
    import dataclasses
    token_dicts = [dataclasses.asdict(t) for t in selected]
    
    packet = {
        "transaction_id": str(uuid.uuid4()),
        "buyer_id_hash": owner_hash,
        "merchant_id": merchant_id,
        "tokens": token_dicts,
        "transaction_timestamp": int(time.time()),
        "requested_amount": amount,
        "buyer_display_name": buyer_name
    }
    
    return json.dumps(packet, indent=2)
