"""
Data models for the Offline Payment Protocol.
Strictly defines the structure of Token and TransactionPackage.
No business logic.
"""
from dataclasses import dataclass
from typing import List


@dataclass
class Token:
    """
    Token structure (Section 5.1):
    {
      "token_id": "UUIDv4",
      "issuer_id": "RuralBank01",
      "owner_id_hash": "SHA256(buyer_id)",
      "denomination": 100,
      "issue_timestamp": 1712345678,
      "expiry_timestamp": 1712518478,
      "signature": "hex_encoded_signature"
    }
    """
    token_id: str
    issuer_id: str
    owner_id_hash: str
    denomination: int
    issue_timestamp: int
    expiry_timestamp: int
    signature: str


@dataclass
class TransactionPackage:
    """
    Buyer Payment Package Structure (Section 4, Step 2):
    {
      "transaction_id": "UUIDv4",
      "buyer_id_hash": "SHA256(buyer_id)",
      "merchant_id": "Merchant123",
      "tokens": [ ... ],
      "transaction_timestamp": 1712349999
    }
    """
    transaction_id: str
    buyer_id_hash: str
    merchant_id: str
    tokens: List[Token]
    transaction_timestamp: int
