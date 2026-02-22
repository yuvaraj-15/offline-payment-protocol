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
from bank import keys as bank_main  # type: ignore[import]

EXPIRY_BUFFER_SECONDS = 60

def _get_master_key(password: str) -> bytes:
    import os
    from shared.paths import WALLET_SALT_PATH  # type: ignore[import]
    if WALLET_SALT_PATH.exists():
        with open(WALLET_SALT_PATH, "rb") as f:
            salt = f.read()
    else:
        WALLET_SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
        key, salt = crypto.derive_key(password)
        with open(WALLET_SALT_PATH, "wb") as f:
            f.write(salt)
        return key

    key, _ = crypto.derive_key(password, salt)
    return key

def get_or_create_identity(password: str, display_name: Optional[str] = None) -> str:
    import os
    from shared.paths import WALLET_SALT_PATH  # type: ignore[import]
    salt_existed_before = WALLET_SALT_PATH.exists()
    key = _get_master_key(password)

    if not salt_existed_before:
        database.init_db()
        new_id = f"Buyer-{uuid.uuid4().hex}"  # Use full UUID per spec, not truncated
        database.save_config("buyer_id", new_id, key)
        if display_name:
            database.save_config("buyer_display_name", display_name, key)
        return new_id

    database.init_db()

    if database.has_config("buyer_id"):
        buyer_id = database.load_config("buyer_id", key)
        if buyer_id is None:
            raise ValueError("Config entry missing after existence check — DB may be corrupt.")
        return buyer_id
    else:
        new_id = f"Buyer-{uuid.uuid4().hex}"  # Use full UUID per spec
        database.save_config("buyer_id", new_id, key)
        if display_name:
            database.save_config("buyer_display_name", display_name, key)
        return new_id

def preload_funds(password: str, amount: int) -> int:
    key = _get_master_key(password)
    buyer_id = get_or_create_identity(password)
    
    try:
        from bank import database as bank_db  # type: ignore[import]
        bank_db.init_db()
        import sqlite3
        try:
            bank_db.create_account(buyer_id, max(amount * 2, 1000))
        except sqlite3.IntegrityError:
            pass

        bank_key = bank_main.load_or_generate_key()
    except (ImportError, AttributeError, OSError):
         bank_key = ec.generate_private_key(ec.SECP256R1())

    owner_hash = derive_owner_hash(buyer_id)
    
    try:
        tokens = issuance.issue_tokens(bank_key, buyer_id, amount)
    except ValueError as e:
        return 0

    database.store_tokens(tokens, key)
    
    return len(tokens)

def get_balance_info(password: str) -> dict:
    key = _get_master_key(password)
    database.expire_stale_tokens()
    tokens = database.list_unspent_tokens(key)
    return {
        "count": len(tokens),
        "total": sum(t.denomination for t in tokens),
        "tokens": tokens
    }

def create_payment_packet(password: str, merchant_id: str, amount: int) -> str:
    key = _get_master_key(password)
    buyer_id = get_or_create_identity(password)
    owner_hash = derive_owner_hash(buyer_id)
    
    buyer_name = "Unknown Customer"
    if database.has_config("buyer_display_name"):
        val = database.load_config("buyer_display_name", key)
        if val:
            buyer_name = val

    database.expire_stale_tokens()
    all_tokens = database.list_unspent_tokens(key)

    now = int(time.time())
    valid_tokens = [t for t in all_tokens if t.expiry_timestamp > now + EXPIRY_BUFFER_SECONDS]
    
    selected = []
    current_sum = 0
    valid_tokens.sort(key=lambda x: x.denomination, reverse=True)
    
    for t in valid_tokens:
        if current_sum >= amount:
            break
        selected.append(t)
        current_sum += t.denomination
        
    if current_sum < amount:
        raise ValueError(f"Insufficient funds. Have {current_sum}, need {amount}")
        
    if current_sum > amount:
        pass

    ids = [t.token_id for t in selected]
    success = database.mark_tokens_spent(ids)
    if not success:
        raise RuntimeError("Atomic State Update Failed. Race condition?")
        
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

def get_local_token_details(password: str) -> List[dict]:
    import json
    import sqlite3
    from cryptography.exceptions import InvalidTag  # type: ignore[import]
    
    key = _get_master_key(password)
    results = []
    
    with database.get_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT token_id, denomination, status, payload FROM tokens").fetchall()
        
    for r in rows:
        token_id = r["token_id"]
        denom = r["denomination"]
        status = r["status"]
        
        issue_ts = 0
        expiry_ts = 0
        
        try:
            json_bytes = crypto.decrypt_blob(key, r["payload"])
            data = json.loads(json_bytes)
            issue_ts = data.get("issue_timestamp", 0)
            expiry_ts = data.get("expiry_timestamp", 0)
        except InvalidTag:
            pass  # Incorrect password or corrupted payload
        except json.JSONDecodeError:
            pass  # Corrupted JSON inside payload
            
        results.append({
            "token_id": token_id,
            "denomination": denom,
            "status": status,
            "issue_timestamp": issue_ts,
            "expiry_timestamp": expiry_ts
        })
        
    return results
