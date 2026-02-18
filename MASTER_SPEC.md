# MASTER_SPEC.md

(Authoritative Protocol Specification – Version 1.0)

You will copy this exactly into `MASTER_SPEC.md`.

---

# MASTER SPECIFICATION

## Software-Only Identity-Bound Offline Payment Protocol

Version: 1.0
Status: Architecture Frozen

---

# 1. SYSTEM PURPOSE

This system defines a **software-only, identity-bound, token-based offline digital payment protocol** designed for rural agricultural marketplaces with intermittent connectivity.

The protocol enables:

* Bank-issued digitally signed tokens
* Fully offline buyer-to-merchant transactions
* Offline merchant signature verification
* Deterministic settlement-phase double-spending detection
* No hardware trust anchors (No TEE, TPM, Secure Element)
* No blockchain or distributed ledger
* Identity-bound (non-anonymous) tokens
* Fixed denomination multiples of ₹10
* Physical change allowed
* Fraud detection during settlement, not prevention offline

This document is the single source of truth.
No module may deviate from this specification.

---

# 2. CRYPTOGRAPHIC PRIMITIVES (LOCKED)

The system SHALL use only:

* ECDSA using curve: NIST P-256
* Hash function: SHA-256
* Symmetric encryption (wallet only): AES-256
* Key derivation (wallet only): PBKDF2-HMAC-SHA256

No alternative curves.
No RSA.
No Ed25519.
No JWT.
No blockchain.
No blind signatures.
No zero-knowledge proofs.

---

# 3. SYSTEM ENTITIES

## 3.1 Issuing Bank (IB)

Responsibilities:

* Generate ECDSA key pair
* Maintain issued token ledger
* Deduct buyer account during preload
* Sign tokens
* Validate settlement submissions
* Detect duplicate token_id
* Credit merchant accounts
* Refund expired unused tokens

The Bank is fully trusted for:

* Issuance integrity
* Settlement correctness
* Ledger consistency

---

## 3.2 Buyer Wallet (B)

Responsibilities:

* Request token preload (online)
* Store tokens encrypted locally
* Select tokens for payment
* Transmit tokens offline
* Delete spent tokens
* Request refund of expired unused tokens

Buyer wallet is NOT trusted to:

* Prevent local duplication
* Prevent file copying
* Prevent offline replay

Fraud risk is bounded by expiry window.

---

## 3.3 Merchant Device (M)

Responsibilities:

* Display static QR
* Receive payment package offline
* Verify ECDSA signatures
* Verify expiry
* Store pending tokens
* Submit tokens during settlement

Merchant does NOT perform fraud adjudication.

---

# 4. FINANCIAL MODEL (LOCKED)

## 4.1 Preload Model

When buyer preloads ₹X:

* ₹X is immediately deducted from buyer’s real bank account.
* Tokens worth ₹X are issued.
* Tokens are marked "issued" in bank ledger.
* This is equivalent to digital ATM withdrawal.

Funds are NOT frozen.
Funds are removed from buyer account immediately.

---

## 4.2 Settlement Model

During merchant settlement:

For each token:

* If token valid and unused:

  * Merchant account is credited full denomination.
  * Token marked "spent".
* If duplicate:

  * Reject second submission.
  * Log fraud event against owner_id_hash.

No partial settlement.

---

## 4.3 Refund Model

If token expires unused:

* Buyer may submit refund request.
* Bank verifies:

  * Token exists
  * Not spent
  * Expired
* Bank credits buyer account.
* Token marked "refunded".

Settlement has priority over refund.
If settlement and refund occur concurrently, the first successful ledger state change (atomic DB transaction) determines the final state.
A token may transition only once from ISSUED → SPENT or ISSUED → REFUNDED.
No reverse transitions allowed.
---

# 5. TOKEN SPECIFICATION (STRICT)

Token structure MUST be:

```json
{
  "token_id": "UUIDv4",
  "issuer_id": "RuralBank01",
  "owner_id_hash": "SHA256(buyer_id)",
  "denomination": 100,
  "issue_timestamp": 1712345678,
  "expiry_timestamp": 1712518478,
  "signature": "hex_encoded_signature"
}
```

---

## 5.1 Field Definitions

* token_id: 128-bit UUIDv4
* issuer_id: constant string identifying issuing bank
* owner_id_hash: SHA256(buyer_id) hex encoded
* denomination: integer multiple of 10
* issue_timestamp: UNIX epoch seconds
* expiry_timestamp: issue_timestamp + 48 hours
* signature: ECDSA signature over canonical hash

---

## 5.2 Allowed Denominations

Valid denominations:

* 10
* 50
* 100
* 200

Minimum transaction unit: ₹10

Market prices must be rounded to nearest ₹10.

Digital change is NOT supported.

---

# 6. CANONICAL HASHING (CRITICAL – MUST MATCH EVERYWHERE)

Signature input MUST be:

SHA256(
token_id ||
issuer_id ||
owner_id_hash ||
denomination ||
issue_timestamp ||
expiry_timestamp
)

Concatenation rules:

* UTF-8 encoding
* No whitespace
* No JSON formatting
* Exact field order above
* Integers converted to decimal string before encoding

Any deviation breaks signature verification.

This rule is frozen.

---

# 7. OFFLINE TRANSACTION PROTOCOL

## Step 1 – Merchant QR

Merchant displays:

```json
{
  "merchant_id": "Merchant123",
  "bluetooth_service_uuid": "..."
}
```

---

## Step 2 – Buyer Payment Package

Buyer sends:

```json
{
  "transaction_id": "UUIDv4",
  "buyer_id_hash": "SHA256(buyer_id)",
  "merchant_id": "Merchant123",
  "tokens": [ ... ],
  "transaction_timestamp": 1712349999
}
```

---

## Step 3 – Merchant Verification

For each token:

1. Recompute canonical hash
2. Verify ECDSA signature
3. Ensure expiry_timestamp ≥ transaction_timestamp
4. Ensure owner_id_hash == buyer_id_hash
5. Ensure token_id not already locally received

If all pass → accept.

---

# 8. EXPIRY POLICY

Validity window: 48 hours from issue.

Important:

* Token must be spent before expiry.
* Merchant may settle after expiry.
* Expiry applies to spending, not settlement.

---

# 9. DOUBLE SPENDING MODEL

System does NOT prevent offline double spending.

Fraud detection occurs at settlement:

If token_id already marked spent:

* Reject duplicate
* Log fraud against owner_id_hash

First valid submission wins.

---

# 10. THREAT MODEL

System protects against:

* Token forgery
* Signature tampering
* Denomination modification
* Duplicate settlement
* Replay within same merchant

System does NOT protect against:

* Offline duplicate spending
* Wallet file copying
* Malware extraction of tokens

Risk bounded by:

* 48-hour expiry
* Low denominations
* Rural use-case

---

# 11. MODULE BOUNDARIES (STRICT)

Role A:

* Wallet
* Merchant
* Crypto utilities
* Offline protocol
* Security testing

Role B:

* Bank server
* Issuance
* Ledger
* Settlement engine
* Fraud detection
* Refund logic

Shared:

* Token schema
* Canonical hashing logic
* Public key format
* Field ordering

No cross-modification without explicit change log.

---

# 12. PROHIBITED CHANGES

Agents must NOT:

* Introduce blockchain
* Introduce anonymity
* Change hashing order
* Change expiry policy
* Modify denomination rules
* Replace ECDSA
* Add hardware trust anchors
* Replace identity-bound model

Any such suggestion must be rejected.

---

# END OF SPECIFICATION