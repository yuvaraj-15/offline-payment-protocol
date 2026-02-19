"""Merchant Core Logic.

Handles Offline Packet Verification and Storage.
Strictly adheres to MASTER_SPEC.md.
"""
import time
import json
import os
from typing import Any

from cryptography.hazmat.primitives import serialization  # type: ignore[import]

from shared.models import Token, TransactionPackage  # type: ignore[import]
from shared.crypto import canonical_hash, verify_signature  # type: ignore[import]
from merchant import database  # type: ignore[import]

def _load_bank_public_key() -> Any:
    """Load the Bank's public key for signature verification."""
    # In a real app, this is hardcoded or trusted-pinned.
    # Here we load from file (exported by Bank).
    path = "bank/public_key.pem"
    if not os.path.exists(path):
        raise RuntimeError("Bank Public Key not found. Bank module must run first.")
        
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def verify_packet(packet_json: str) -> dict:
    """Parse and Verify Payment Packet.
    
    Checks:
    1. Structure
    2. Ownership (packet.buyer == token.owner)
    3. Expiry (token.expiry >= packet.ts)
    4. Signatures (Bank key)
    
    Returns: packet dict if valid. Raises ValueError if invalid.
    """
    try:
        data = json.loads(packet_json)
        # Basic field check (loose)
        # We rely on strict checks below
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format")

    tx_id = data.get("transaction_id")
    buyer_hash = data.get("buyer_id_hash")
    tx_ts = data.get("transaction_timestamp")
    tokens_data = data.get("tokens", [])
    
    if not tokens_data:
        raise ValueError("Empty token list")

    bank_pub = _load_bank_public_key()
    
    for t_data in tokens_data:
        # Reconstruct Token Object
        # Note: shared.models.Token expects specific types
        # t_data from JSON has strings/ints.
        try:
            token = Token(**t_data)
        except TypeError:
             raise ValueError("Malformed token structure")
             
        # 1. Ownership Check
        if token.owner_id_hash != buyer_hash:
            raise ValueError(f"Token {token.token_id} belongs to different owner")
            
        # 2. Expiry Check (Strict >=)
        if token.expiry_timestamp < tx_ts:
            raise ValueError(f"Token {token.token_id} expired at {token.expiry_timestamp}")
            
        # 3. Signature Verification
        # Recalculate hash (STRICT SECTION 6)
        msg_hash = canonical_hash(token)
        
        if not verify_signature(bank_pub, msg_hash, token.signature):
            raise ValueError(f"Invalid Bank Signature for token {token.token_id}")

    return data


def process_payment(packet_json: str) -> bool:
    """Verify and Store Payment.
    
    Returns:
        True: Accepted and Stored.
        False: Rejected (Duplicate).
    Raises:
        ValueError: Invalid Packet.
    """
    # 1. Verify
    packet = verify_packet(packet_json)
    
    # 2. Store Atomic
    committed = database.save_transaction(packet)
    
    if not committed:
        # Log suspected double spend? 
        # For MVP returning False implies "Already Received".
        pass
        
    return committed
