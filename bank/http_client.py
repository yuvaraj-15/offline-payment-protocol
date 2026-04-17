import os
import json
from typing import List

import httpx

from shared.models import Token

from bank import keys as bank_keys 
from bank import issuance as bank_issuance 


def _parse_tokens(token_dicts: List[dict]) -> List[Token]:
    tokens: List[Token] = []
    for td in token_dicts:
        tokens.append(Token(**td))
    return tokens


def issue_tokens(buyer_id: str, amount: int, request_id: str | None = None) -> List[Token]:
    """Issue tokens either via HTTP to central bank (if BANK_HTTP_URL set) or via local library call.

    Returns list of Token objects.
    """
    bank_url = os.getenv("BANK_HTTP_URL")
    api_key = os.getenv("BANK_API_KEY")

    if bank_url:
        url = bank_url.rstrip("/") + "/api/v1/issue"
        payload = {"buyer_id": buyer_id, "amount": amount}
        if request_id:
            payload["request_id"] = request_id

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        token_dicts = data.get("tokens", [])
        return _parse_tokens(token_dicts)

    # Fallback to local issuance
    bank_key = bank_keys.load_or_generate_key()
    return bank_issuance.issue_tokens(bank_key, buyer_id, amount)


def settle_transaction(transaction_package: dict) -> dict:
    """Post a transaction package to the bank settlement endpoint. Returns the JSON response dict or calls local settlement.
    """
    bank_url = os.getenv("BANK_HTTP_URL")
    api_key = os.getenv("BANK_API_KEY")

    if bank_url:
        url = bank_url.rstrip("/") + "/api/v1/settle"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        resp = httpx.post(url, json=transaction_package, headers=headers, timeout=30.0)
        resp.raise_for_status()
        return resp.json()

    from bank import settlement as bank_settlement 
    from cryptography.hazmat.primitives.asymmetric import ec 
    bank_key = bank_keys.load_or_generate_key()
    bank_pub = bank_key.public_key()

    from shared.models import TransactionPackage, Token as SharedToken 
    tokens = [SharedToken(**t) for t in transaction_package.get("tokens", [])]
    pkg = TransactionPackage(
        transaction_id=transaction_package.get("transaction_id"),
        buyer_id_hash=transaction_package.get("buyer_id_hash"),
        merchant_id=transaction_package.get("merchant_id"),
        tokens=tokens,
        transaction_timestamp=transaction_package.get("transaction_timestamp"),
        requested_amount=transaction_package.get("requested_amount", 0),
        buyer_display_name=transaction_package.get("buyer_display_name", "")
    )

    return bank_settlement.settle_transaction(bank_pub, pkg)
