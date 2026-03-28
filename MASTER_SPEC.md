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

# 13. DEPLOYMENT AND RUNNING (GUI AND SERVER)

This repository provides both command-line and desktop GUI interfaces for the Wallet and Merchant, plus an optional centralized HTTP Bank service for online issuance and settlement. The following rules describe supported runtime modes and developer guidance.

13.1 Supported Modes

* Offline-only mode (no central bank): Wallet and Merchant run locally, using local SQLite databases and local issuance routines for testing.
* Centralized Bank mode (optional): A FastAPI-based HTTP Bank exposes issuance and settlement endpoints. Wallet and Merchant may be configured to call the central bank via an HTTP client wrapper; when not configured they fall back to local library calls.

13.2 Command-line vs Desktop GUI

* CLI tools (in `scripts/`) provide a reproducible terminal-driven flow. They are suitable for headless environments and automated tests.
* Desktop GUI (Tkinter) provides a convenience front-end for manual demonstrations. GUI is a thin wrapper around the same `wallet.core` and `merchant.settlement` logic. GUI must not change protocol rules.

13.3 Recommended developer run steps (short)

1. Create and activate a Python virtual environment.
2. Install dependencies: `cryptography`, `fastapi`, `uvicorn`, `httpx` (only required for HTTP mode).
3. Start the bank server (optional):
  - `export BANK_ALLOW_DEV=true` (dev-only) then `python3 scripts/bank_server.py` or use uvicorn with reload.
4. Launch GUI (or CLI): `python3 scripts/gui_launcher.py` or `python3 scripts/wallet_app.py` / `python3 scripts/merchant_app.py`.

Always run bank server in the same Python environment as the client GUI/CLI when testing HTTP mode.

# 14. CENTRALIZED BANK HTTP API (OPTIONAL)

This project includes an optional HTTP API for the Bank to facilitate centralized issuance and settlement. This API is a convenience layer and does not change the canonical protocol. Clients MUST be backward compatible with local-mode operation.

14.1 Endpoints (summary)

* GET /health — basic health check; returns 200 and {"status":"ok"}.
* GET /api/v1/public_key — returns PEM public key for signature verification (may be protected by API key).
* POST /api/v1/issue — request issuance of tokens. Payload: {"buyer_id": "Buyer-...", "amount": 100, "request_id": "optional"}. Returns issued tokens array on success.
* POST /api/v1/settle — submit a transaction package for settlement. Payload: transaction package JSON defined in §7. Returns per-token settlement results.

14.2 Security and Idempotency

* API calls SHOULD be protected via an API key (header `X-API-Key`) in production. A development override (`BANK_ALLOW_DEV=true`) exists for local testing only.
* The server SHOULD implement idempotency for issuance (deduplicate by `request_id`) and settlement (deduplicate by `transaction_id`), but the presence of a `request_id`/`transaction_id` is optional for basic clients. Implementations MUST handle retries gracefully (at-most-once semantics are not enforced by the spec; clients should implement retry/backoff).

14.3 Client wrapper contract

* Clients use a wrapper that: if `BANK_HTTP_URL` is set, performs HTTP requests; otherwise calls local library functions (preserves offline-first behavior).
* The wrapper MUST preserve data types required by the server: `amount` must be an integer (multiples of 10), `buyer_id` must be the exact buyer identifier used in the wallet database.

# 15. GUI SPEC (DEMONSTRATION-ONLY)

The GUI is a demonstration tool and not part of the core protocol. It must follow these constraints:

15.1 Wallet GUI

* Identity: allows creating or loading a wallet. When creating, GUI prompts for a password and a display name. The wallet stores a local salt and encrypted config (`buyer_id` and optional `buyer_display_name`).
* Preload Funds: prompts for password and amount, calls `wallet.core.preload_funds` and writes tokens into the local encrypted token store.
* View Tokens: lists local tokens (id prefix, denomination, status, expiry).
* Pay Merchant: creates a payment packet using local tokens and sends it over the merchant transport.

15.2 Merchant GUI

* Identity: create/load merchant id and display name.
* Payment Server: starts merchant transport in headless mode (spawns a subprocess) to accept wallet connections.
* View Transactions: inspect local `transactions` table and pending tokens.
* Settle Pending: triggers `merchant.settlement.settle_pending_transactions()` which either posts to central bank (if configured) or performs local settlement logic.

15.3 Thread-safety and UX

* GUI must not call Tkinter APIs from background threads. All UI updates (message boxes, labels) must be scheduled on the main Tk thread.
* GUI must surface errors returned by underlying library functions (wrong password, invalid amount, network error) in a clear dialog and must not swallow exceptions silently.

# 16. DEVELOPMENT NOTES (CHANGELOG AND TESTING)

* The canonical protocol (hashing, token fields, cryptography, denominations, expiry) is frozen and cannot be changed without an explicit specification revision.
* GUI, CLI, and HTTP convenience layers are non-authoritative interfaces and may evolve. Any functional change that affects token fields, canonical hashing, or the cryptographic contract MUST be reflected here and rejected if it alters the frozen rules.
* Unit and integration tests MUST include: verification of canonical hash, signature generation/verification, issuance/settlement atomicity, refund paths, and end-to-end token lifecycle in both local and HTTP modes.

---

# END OF SPECIFICATION