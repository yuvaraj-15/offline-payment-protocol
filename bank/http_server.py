import os
import dataclasses
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, JSONResponse

from bank import keys as bank_keys  
from bank import database as bank_db  
from bank import issuance as bank_issuance  
from bank import settlement as bank_settlement  

from shared.models import Token, TransactionPackage  

app = FastAPI(title="Offline Payment Bank API")

API_KEY = os.getenv("BANK_API_KEY")
ALLOW_DEV = os.getenv("BANK_ALLOW_DEV", "false").lower() in ("1", "true", "yes")


async def _require_api_key(request: Request):
    if API_KEY and not ALLOW_DEV:
        header = request.headers.get("x-api-key")
        if header != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")


@app.on_event("startup")
def startup():
    bank_db.init_db()
    bank_keys.load_or_generate_key()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/public_key")
async def public_key(request: Request):
    await _require_api_key(request)
    pub_path = bank_keys.PUB_KEY_FILE if hasattr(bank_keys, 'PUB_KEY_FILE') else None
    try:
        pk = bank_keys.load_or_generate_key().public_key()
        from cryptography.hazmat.primitives import serialization  
        pem = pk.public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        return PlainTextResponse(pem.decode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load public key: {e}")


@app.post("/api/v1/issue")
async def issue(request: Request):
    await _require_api_key(request)
    payload = await request.json()
    buyer_id = payload.get("buyer_id")
    amount = payload.get("amount")
    request_id = payload.get("request_id")
    if not buyer_id or not isinstance(amount, int):
        raise HTTPException(status_code=400, detail="buyer_id and integer amount are required")

    try:
        bank_db.init_db()
        bank_key = bank_keys.load_or_generate_key()
        tokens = bank_issuance.issue_tokens(bank_key, buyer_id, amount)
        token_dicts = [dataclasses.asdict(t) for t in tokens]
        return JSONResponse({"request_id": request_id, "issued_amount": amount, "tokens": token_dicts})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/settle")
async def settle(request: Request):
    await _require_api_key(request)
    payload = await request.json()

    tx_id = payload.get("transaction_id")
    if not tx_id:
        raise HTTPException(status_code=400, detail="transaction_id required")

    try:
        bank_db.init_db()
        bank_key = bank_keys.load_or_generate_key()
        bank_pub = bank_key.public_key()

        tokens = [Token(**t) for t in payload.get("tokens", [])]
        pkg = TransactionPackage(
            transaction_id=payload.get("transaction_id"),
            buyer_id_hash=payload.get("buyer_id_hash"),
            merchant_id=payload.get("merchant_id"),
            tokens=tokens,
            transaction_timestamp=payload.get("transaction_timestamp"),
            requested_amount=payload.get("requested_amount", 0),
            buyer_display_name=payload.get("buyer_display_name", "")
        )

        results = bank_settlement.settle_transaction(bank_pub, pkg)
        return JSONResponse({"transaction_id": tx_id, "results": results})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
