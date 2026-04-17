import time
import json
import os
from typing import Any

from cryptography.hazmat.primitives import serialization  

from shared.models import Token, TransactionPackage  
from shared.crypto import canonical_hash, verify_signature  
from merchant import database  

def _load_bank_public_key() -> Any:
    
    from shared.paths import BANK_PUB_KEY_PATH  
    path = str(BANK_PUB_KEY_PATH)
    if not os.path.exists(path):
        raise RuntimeError("Bank Public Key not found. Bank module must run first.")
        
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())

def verify_packet(packet_json: str, merchant_id: str) -> dict:
    
    try:
        data = json.loads(packet_json)

    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format")

    tx_id = data.get("transaction_id")
    buyer_hash = data.get("buyer_id_hash")
    tx_ts = data.get("transaction_timestamp")
    req_amount = data.get("requested_amount")
    tokens_data = data.get("tokens", [])
    
    if not tokens_data:
        raise ValueError("Empty token list")

    if data.get("merchant_id") != merchant_id:
        raise ValueError("Merchant ID mismatch")
        
    if req_amount is None or not isinstance(req_amount, int) or req_amount <= 0:
        raise ValueError("Invalid requested_amount")

    bank_pub = _load_bank_public_key()
    
    total_token_value = 0
    
    for t_data in tokens_data:
        
        try:
            token = Token(**t_data)
        except TypeError:
             raise ValueError("Malformed token structure")
             
        if token.owner_id_hash != buyer_hash:
            raise ValueError(f"Token {token.token_id} belongs to different owner")
            
        if token.issue_timestamp > tx_ts:
            raise ValueError("Transaction timestamp earlier than token issuance")

        if token.expiry_timestamp < tx_ts:
            raise ValueError(f"Token {token.token_id} expired at {token.expiry_timestamp}")
            
        msg_hash = canonical_hash(token)
        
        if not verify_signature(bank_pub, msg_hash, token.signature):
            raise ValueError(f"Invalid Bank Signature for token {token.token_id}")
            
        total_token_value += token.denomination

    if total_token_value < req_amount:
        raise ValueError(f"Tokens insufficient. Provided: {total_token_value}, Requested: {req_amount}")

    return data

def process_payment(packet_json: str, merchant_id: str) -> bool:
    
    packet = verify_packet(packet_json, merchant_id)
    
    committed = database.save_transaction(packet)
    
    if not committed:
        pass
        
    return committed
