from dataclasses import dataclass
from typing import List

@dataclass
class Token:
    token_id: str
    issuer_id: str
    owner_id_hash: str
    denomination: int
    issue_timestamp: int
    expiry_timestamp: int
    signature: str

@dataclass
class TransactionPackage:
    transaction_id: str
    buyer_id_hash: str
    merchant_id: str
    tokens: List[Token]
    transaction_timestamp: int
    requested_amount: int
    buyer_display_name: str
