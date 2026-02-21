"""
FULL SYSTEM REGRESSION SWEEP
Covers: Wallet, Merchant, Bank, Transport, and Final Invariant Checks.
DO NOT MODIFY CODE — ANALYSIS AND REPORTING ONLY.
"""
import os, sys, json, time, copy, socket, threading, traceback, hashlib
os.environ["MERCHANT_TEST_LOOPBACK"] = "1"

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bank import database as bank_db, issuance as bank_issuance  # type: ignore[import]
from demos import bank_demo as bank_main
from bank import settlement as bank_settlement, refund as bank_refund  # type: ignore[import]
from merchant import core as merch_core, database as merch_db  # type: ignore[import]
from wallet import core as wallet_core, database as wallet_db  # type: ignore[import]
from shared import crypto as shared_crypto, models as shared_models  # type: ignore[import]
from shared.models import Token, TransactionPackage  # type: ignore[import]

# ── Helpers ───────────────────────────────────────────────────────────────────
results = []

def r(section, name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((section, name, status, detail))
    marker = "  [+]" if passed else "  [X]"
    safe_detail = detail.encode("ascii", errors="replace").decode("ascii")
    print(f"{marker} [{section}] {name}" + (f" -- {safe_detail}" if safe_detail else ""))

def clean_all():
    """Reset wallet, merchant, and bank state."""
    wallet_db.init_db(reset=True)
    merch_db.init_db(reset=True)
    bank_db.init_db(reset=True)
    for f in ["wallet/.salt", "wallet/wallet.db"]:
        if os.path.exists(f): os.remove(f)

def preload(amount=500, pwd="sweep_pass"):
    """Convenience preload wrapper."""
    buyer_id = wallet_core.get_or_create_identity(pwd)
    try:
        bank_db.create_account(buyer_id, max(amount * 2, 1000))
    except Exception:
        pass
    return wallet_core.preload_funds(pwd, amount)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION A — WALLET BEHAVIOUR
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("SECTION A — WALLET BEHAVIOUR")
print("="*60)

# ── A1: Fresh preload ──────────────────────────────────────────────────────────
clean_all()
try:
    n = preload(500)
    wallet_db.expire_stale_tokens()
    tokens = wallet_db.list_unspent_tokens(wallet_core._get_master_key("sweep_pass"))
    total = sum(t.denomination for t in tokens)
    from shared.constants import ALLOWED_DENOMINATIONS  # type: ignore[import]
    denom_ok = all(t.denomination in ALLOWED_DENOMINATIONS for t in tokens)
    r("A1", "Correct token count returned", n > 0, f"issued={n}")
    r("A1", "All denominations valid", denom_ok)
    r("A1", "Balance = 500", total == 500, f"total={total}")
except Exception as e:
    r("A1", "Fresh preload", False, str(e))

# ── A2: Double preload — no collision ──────────────────────────────────────────
try:
    n2 = preload(200)
    wallet_db.expire_stale_tokens()
    tokens2 = wallet_db.list_unspent_tokens(wallet_core._get_master_key("sweep_pass"))
    ids = [t.token_id for t in tokens2]
    r("A2", "No duplicate token_id after double preload", len(ids) == len(set(ids)),
      f"tokens={len(ids)}, unique={len(set(ids))}")
    r("A2", "Balance = 700 after cumulative preloads",
      sum(t.denomination for t in tokens2) == 700,
      f"total={sum(t.denomination for t in tokens2)}")
except Exception as e:
    r("A2", "Double preload", False, str(e))

# ── A3: Wrong password ─────────────────────────────────────────────────────────
try:
    # Use a fresh identity so wrong key decryption is detectable
    clean_all()
    preload(100, "correct_pass")
    # Attempt payment using wrong password — _get_master_key will derive wrong key
    # list_unspent_tokens will raise ValueError on decrypt failure
    try:
        wallet_core.create_payment_packet("wrong_pass", "SomeMerch", 100)
        r("A3", "Wrong password rejected before payment", False, "No error raised")
    except (ValueError, Exception):
        # Check tokens are still UNSPENT (not SPENT)
        import sqlite3
        conn = sqlite3.connect(wallet_db.DB_PATH)
        row = conn.execute("SELECT COUNT(*) FROM tokens WHERE status='SPENT'").fetchone()
        conn.close()
        spent_count = row[0]
        r("A3", "Wrong password rejected before payment", True)
        r("A3", "No tokens marked SPENT on wrong password", spent_count == 0,
          f"spent={spent_count}")
except Exception as e:
    r("A3", "Wrong password test", False, str(e))

# ── A4: Expiry sweep ───────────────────────────────────────────────────────────
try:
    clean_all()
    orig_expiry = bank_issuance.EXPIRY_SECONDS
    bank_issuance.EXPIRY_SECONDS = 1  # 1-second expiry
    orig_buffer = wallet_core.EXPIRY_BUFFER_SECONDS
    wallet_core.EXPIRY_BUFFER_SECONDS = 0

    preload(100, "sweep_pass")
    time.sleep(2)  # let tokens expire

    wallet_db.expire_stale_tokens()
    import sqlite3
    conn = sqlite3.connect(wallet_db.DB_PATH)
    exp = conn.execute("SELECT COUNT(*) FROM tokens WHERE status='EXPIRED'").fetchone()[0]
    unspent = conn.execute("SELECT COUNT(*) FROM tokens WHERE status='UNSPENT'").fetchone()[0]
    conn.close()

    r("A4", "UNSPENT to EXPIRED transition executed", exp > 0, f"expired={exp}")
    r("A4", "No UNSPENT tokens remain after sweep", unspent == 0, f"unspent={unspent}")

    try:
        wallet_core.create_payment_packet("sweep_pass", "M", 100)
        r("A4", "Expired tokens cannot be selected", False, "Payment packet created — should have failed")
    except (ValueError, RuntimeError):
        r("A4", "Expired tokens cannot be selected", True)

    bank_issuance.EXPIRY_SECONDS = orig_expiry
    wallet_core.EXPIRY_BUFFER_SECONDS = orig_buffer
except Exception as e:
    r("A4", "Expiry sweep", False, str(e))

# ── A5: Network failure after marking SPENT ────────────────────────────────────
try:
    clean_all()
    preload(100, "sweep_pass")
    wallet_db.expire_stale_tokens()
    all_t = wallet_db.list_unspent_tokens(wallet_core._get_master_key("sweep_pass"))
    ids = [t.token_id for t in all_t[:1]]

    # Manually mark spent (simulating what create_payment_packet does)
    ok = wallet_db.mark_tokens_spent(ids)
    r("A5", "Tokens successfully marked SPENT before send", ok)

    # Now try to use them again
    wallet_db.expire_stale_tokens()
    still_unspent = wallet_db.list_unspent_tokens(wallet_core._get_master_key("sweep_pass"))
    still_ids = {t.token_id for t in still_unspent}
    r("A5", "SPENT tokens not available in UNSPENT list", all(i not in still_ids for i in ids))

    # Try marking them spent again — should return False (no UNSPENT match)
    ok2 = wallet_db.mark_tokens_spent(ids)
    r("A5", "mark_tokens_spent returns False for already-SPENT tokens", not ok2)
except Exception as e:
    r("A5", "Network failure / token reuse", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION B — MERCHANT VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("SECTION B — MERCHANT VERIFICATION")
print("="*60)

MERCH_ID = "SweepMerchant"

def make_packet(amount=100, merchant_id=MERCH_ID, pwd="sweep_pass"):
    clean_all()
    preload(amount, pwd)
    return wallet_core.create_payment_packet(pwd, merchant_id, amount)

# ── B1: Normal payment ─────────────────────────────────────────────────────────
try:
    pkt_json = make_packet()
    merch_db.init_db(reset=True)
    result = merch_core.process_payment(pkt_json, MERCH_ID)
    r("B1", "Normal payment accepted", result is True)

    import sqlite3
    conn = sqlite3.connect(merch_db.DB_PATH)
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    tok_count = conn.execute("SELECT COUNT(*) FROM received_tokens").fetchone()[0]
    conn.close()
    r("B1", "Transaction row inserted", tx_count == 1, f"tx_rows={tx_count}")
    r("B1", "Token rows inserted", tok_count > 0, f"tok_rows={tok_count}")
except Exception as e:
    r("B1", "Normal payment", False, str(e))

# ── B2: Replay same packet ─────────────────────────────────────────────────────
try:
    pkt_json = make_packet(100)
    merch_db.init_db(reset=True)
    r1 = merch_core.process_payment(pkt_json, MERCH_ID)
    r2 = merch_core.process_payment(pkt_json, MERCH_ID)
    r("B2", "First insertion accepted", r1 is True)
    r("B2", "Replay rejected", r2 is False)

    import sqlite3
    conn = sqlite3.connect(merch_db.DB_PATH)
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    r("B2", "No duplicate transaction row inserted", tx_count == 1, f"tx_rows={tx_count}")
except Exception as e:
    r("B2", "Replay test", False, str(e))

# ── B3: Merchant ID mismatch ───────────────────────────────────────────────────
try:
    pkt_json = make_packet(100, "CorrectMerchant")
    pkt = json.loads(pkt_json)
    pkt["merchant_id"] = "EvilMerchant"
    merch_db.init_db(reset=True)
    try:
        merch_core.process_payment(json.dumps(pkt), "CorrectMerchant")
        r("B3", "Merchant ID mismatch rejected", False, "No error raised")
    except ValueError as e:
        r("B3", "Merchant ID mismatch rejected", "mismatch" in str(e).lower(), str(e))
except Exception as e:
    r("B3", "Merchant ID mismatch", False, str(e))

# ── B4: Pre-issuance timestamp ─────────────────────────────────────────────────
try:
    pkt_json = make_packet(100)
    pkt = json.loads(pkt_json)
    # Set tx timestamp before any token was issued
    pkt["transaction_timestamp"] = pkt["tokens"][0]["issue_timestamp"] - 1
    merch_db.init_db(reset=True)
    try:
        merch_core.process_payment(json.dumps(pkt), MERCH_ID)
        r("B4", "Pre-issuance timestamp rejected", False, "No error raised")
    except ValueError as e:
        r("B4", "Pre-issuance timestamp rejected", "earlier" in str(e).lower() or "issuance" in str(e).lower(), str(e))
except Exception as e:
    r("B4", "Pre-issuance timestamp", False, str(e))

# ── B5: Expired token ──────────────────────────────────────────────────────────
try:
    pkt_json = make_packet(100)
    pkt = json.loads(pkt_json)
    # Set tx timestamp beyond expiry
    pkt["transaction_timestamp"] = pkt["tokens"][0]["expiry_timestamp"] + 100
    merch_db.init_db(reset=True)
    try:
        merch_core.process_payment(json.dumps(pkt), MERCH_ID)
        r("B5", "Expired token rejected by merchant", False, "No error raised")
    except ValueError as e:
        r("B5", "Expired token rejected by merchant", "expir" in str(e).lower(), str(e))
except Exception as e:
    r("B5", "Expired token", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION C — BANK BEHAVIOUR
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("SECTION C — BANK BEHAVIOUR")
print("="*60)

def make_transaction_package(amount=100, merchant_id="BankMerch", buyer_id="BankBuyer"):
    """Build a TransactionPackage directly via the bank issuance API."""
    bank_db.init_db(reset=True)
    try: bank_db.create_account(buyer_id, amount * 2)
    except Exception: pass
    try: bank_db.create_account(merchant_id, 0)
    except Exception: pass

    bank_key = bank_main.load_or_generate_key()
    tokens = bank_issuance.issue_tokens(bank_key, buyer_id, amount)
    pkg = TransactionPackage(
        transaction_id="tx-sweep-" + str(int(time.time())),
        buyer_id_hash=shared_crypto.derive_owner_hash(buyer_id),
        merchant_id=merchant_id,
        tokens=tokens,
        transaction_timestamp=int(time.time()),
        requested_amount=amount,
        buyer_display_name=buyer_id
    )
    return bank_key.public_key(), pkg

# ── C1: Settlement success ─────────────────────────────────────────────────────
try:
    pub_key, pkg = make_transaction_package(100)
    try: bank_db.create_account("BankMerch", 0)
    except Exception: pass

    results_map = bank_settlement.settle_transaction(pub_key, pkg)
    all_settled = all(v == "SETTLED" for v in results_map.values())
    r("C1", "All tokens SETTLED", all_settled, str(results_map))

    import sqlite3
    conn = sqlite3.connect(bank_db.DB_PATH)
    merch_bal = conn.execute(
        "SELECT balance FROM accounts WHERE user_id='BankMerch'"
    ).fetchone()
    conn.close()
    credit_ok = merch_bal is not None and merch_bal[0] == 100
    r("C1", "Merchant credited once for total denomination", credit_ok,
      f"balance={merch_bal[0] if merch_bal else 'None'}")
except Exception as e:
    r("C1", "Settlement success", False, traceback.format_exc())

# ── C2: Duplicate settlement ───────────────────────────────────────────────────
try:
    pub_key, pkg = make_transaction_package(100)
    try: bank_db.create_account("BankMerch", 0)
    except Exception: pass
    bank_settlement.settle_transaction(pub_key, pkg)  # first
    res2 = bank_settlement.settle_transaction(pub_key, pkg)  # second
    all_rejected = all(v in ("REJECTED_DUPLICATE", "ROLLED_BACK") for v in res2.values())
    r("C2", "Re-settlement fully rejected", all_rejected, str(res2))
except Exception as e:
    r("C2", "Duplicate settlement", False, str(e))

# ── C3: Partial package corruption (one already SPENT) ─────────────────────────
try:
    pub_key, pkg = make_transaction_package(200)
    try: bank_db.create_account("BankMerch", 0)
    except Exception: pass

    # Manually SPEND the first token
    import sqlite3
    conn = sqlite3.connect(bank_db.DB_PATH)
    conn.execute(
        "UPDATE tokens SET status='SPENT' WHERE token_id=?",
        (pkg.tokens[0].token_id,)
    )
    conn.commit()
    conn.close()

    # Now settle — first token is already SPENT, should cause full rollback
    res = bank_settlement.settle_transaction(pub_key, pkg)
    any_settled = any(v == "SETTLED" for v in res.values())
    r("C3", "Full rollback on partial corruption (no SETTLED tokens)", not any_settled, str(res))

    # Confirm other tokens are NOT SPENT (rollback worked)
    conn = sqlite3.connect(bank_db.DB_PATH)
    for t in pkg.tokens[1:]:
        row = conn.execute("SELECT status FROM tokens WHERE token_id=?", (t.token_id,)).fetchone()
        tok_status = row[0] if row else None
        r("C3", f"Token {t.token_id[:8]}… still ISSUED (rolled back)", tok_status == "ISSUED",
          f"status={tok_status}")
    conn.close()
except Exception as e:
    r("C3", "Partial package corruption", False, traceback.format_exc())

# ── C4: Refund logic ───────────────────────────────────────────────────────────
try:
    bank_db.init_db(reset=True)
    buyer_id = "RefundBuyer"
    try: bank_db.create_account(buyer_id, 500)
    except Exception: pass

    orig_expiry = bank_issuance.EXPIRY_SECONDS
    bank_issuance.EXPIRY_SECONDS = 1
    bank_key = bank_main.load_or_generate_key()
    tokens = bank_issuance.issue_tokens(bank_key, buyer_id, 100)
    bank_issuance.EXPIRY_SECONDS = orig_expiry

    # Before expiry → should FAIL
    res_before = bank_refund.request_refund(buyer_id, tokens[0].token_id)
    r("C4", "Refund before expiry rejected", res_before == "FAILED_NOT_EXPIRED",
      f"result={res_before}")

    time.sleep(2)  # expire

    # After expiry → should REFUND
    import sqlite3
    conn = sqlite3.connect(bank_db.DB_PATH)
    bal_before = conn.execute("SELECT balance FROM accounts WHERE user_id=?", (buyer_id,)).fetchone()[0]
    conn.close()

    res_after = bank_refund.request_refund(buyer_id, tokens[0].token_id)
    r("C4", "Refund after expiry succeeds", res_after == "REFUNDED", f"result={res_after}")

    conn = sqlite3.connect(bank_db.DB_PATH)
    bal_after = conn.execute("SELECT balance FROM accounts WHERE user_id=?", (buyer_id,)).fetchone()[0]
    stat = conn.execute("SELECT status FROM tokens WHERE token_id=?", (tokens[0].token_id,)).fetchone()[0]
    conn.close()
    r("C4", "Buyer balance credited after refund",
      bal_after == bal_before + tokens[0].denomination,
      f"before={bal_before} after={bal_after} denom={tokens[0].denomination}")
    r("C4", "Token status = REFUNDED", stat == "REFUNDED", f"status={stat}")
except Exception as e:
    r("C4", "Refund logic", False, traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION D — TRANSPORT
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("SECTION D — TRANSPORT")
print("="*60)

from merchant import transport as merch_transport  # type: ignore[import]
from wallet import transport as wallet_transport  # type: ignore[import]

def start_merch_server(mid="TransMerch"):
    """Start merchant in headless loopback mode, return (ip, port, stop_event)."""
    bank_db.init_db(reset=True)
    merch_db.init_db(reset=True)
    try: bank_db.create_account("TransBuyer", 2000)
    except Exception: pass
    # Preload wallet so packet is ready
    clean_all()
    preload(200, "sweep_pass")

    import socket as _s
    srv = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    srv.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                srv.settimeout(0.5)
                cs, addr = srv.accept()
                t = threading.Thread(
                    target=merch_transport.handle_client,
                    args=(cs, addr, mid),
                    daemon=True
                )
                t.start()
            except Exception:
                pass
        srv.close()

    threading.Thread(target=loop, daemon=True).start()
    return "127.0.0.1", port, stop

# -- D1 & D2: Normal TCP / Loopback
try:
    # Preload BEFORE starting server (start_merch_server calls clean_all)
    ip, port, stop = start_merch_server("TransMerch")
    # start_merch_server already called clean_all + preload(200)
    # The wallet tokens are in UNSPENT state — create the packet now
    time.sleep(0.2)
    pkt_json = wallet_core.create_payment_packet("sweep_pass", "TransMerch", 100)
    pkt_compact = json.dumps(json.loads(pkt_json))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((pkt_compact + "\n").encode())
        s.settimeout(5)
        ack = s.recv(64).decode().strip()

    r("D1/D2", "Loopback TCP - ACK_SUCCESS received", ack == "ACK_SUCCESS", f"ack={ack}")
    stop.set()
except Exception as e:
    r("D1/D2", "Normal TCP/Loopback", False, str(e))

# ── D3: Connect timeout ────────────────────────────────────────────────────────
try:
    # Port 19999 is not listening — should timeout/refuse
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", 19999))
            r("D3", "Connection refused / timeout handled", False, "Connected unexpectedly")
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            r("D3", "Connection refused / timeout handled", True, type(e).__name__)
except Exception as e:
    r("D3", "Connect timeout", False, str(e))

# ── D4: Malformed JSON ─────────────────────────────────────────────────────────
try:
    ip4, port4, stop4 = start_merch_server("MalMerch")
    time.sleep(0.2)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip4, port4))
        s.sendall(b"not valid json\n")
        s.settimeout(5)
        ack4 = s.recv(64).decode().strip()
    r("D4", "Malformed JSON - ACK_REJECT", ack4 == "ACK_REJECT", f"ack={ack4}")
    stop4.set()
except Exception as e:
    r("D4", "Malformed JSON", False, str(e))

# ── D5: Missing newline delimiter ──────────────────────────────────────────────
try:
    ip5, port5, stop5 = start_merch_server("NLMerch")
    time.sleep(0.2)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip5, port5))
        # Send without newline, then close — server should timeout or see disconnect
        s.sendall(b'{"incomplete": true}')
        s.settimeout(0.3)
        try:
            ack5 = s.recv(64).decode().strip()
            r("D5", "Missing newline — no premature ACK", False, f"ack={ack5}")
        except socket.timeout:
            r("D5", "Missing newline — server waits correctly (no premature ACK)", True)
    stop5.set()
except Exception as e:
    r("D5", "Missing newline delimiter", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# FINAL INVARIANT CHECKS
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("FINAL INVARIANT CHECKS")
print("="*60)

# canonical_hash unchanged / deterministic
try:
    bank_db.init_db(reset=True)
    try: bank_db.create_account("HashBuyer", 200)
    except Exception: pass
    bank_key = bank_main.load_or_generate_key()
    tokens_h = bank_issuance.issue_tokens(bank_key, "HashBuyer", 100)
    t0 = tokens_h[0]
    h1 = shared_crypto.canonical_hash(t0)
    h2 = shared_crypto.canonical_hash(t0)
    r("F1", "canonical_hash is deterministic", h1 == h2)

    # Confirm signature field is excluded from hash
    import dataclasses
    t_nosig = dataclasses.replace(t0, signature="")
    h_nosig = shared_crypto.canonical_hash(t_nosig)
    r("F1", "Signature field excluded from canonical_hash", h1 == h_nosig)
except Exception as e:
    r("F1", "canonical_hash", False, str(e))

# Signature verify deterministic
try:
    pub = bank_main.load_or_generate_key().public_key()
    msg = shared_crypto.canonical_hash(tokens_h[0])
    sig = tokens_h[0].signature
    v1 = shared_crypto.verify_signature(pub, msg, sig)
    v2 = shared_crypto.verify_signature(pub, msg, sig)
    r("F2", "verify_signature deterministic", v1 == v2 == True)
    bad_ver = shared_crypto.verify_signature(pub, msg, "deadbeef" * 32)
    r("F2", "Invalid signature correctly rejected", bad_ver is False)
except Exception as e:
    r("F2", "Signature verification", False, str(e))

# No global merchant_id remains
try:
    import importlib, inspect
    src = inspect.getsource(merch_core)
    r("F3", "No LOCAL_MERCHANT_ID global in merchant.core", "LOCAL_MERCHANT_ID" not in src)
    trans_src = inspect.getsource(merch_transport)
    r("F3", "No LOCAL_MERCHANT_ID assignment in merchant.transport", "LOCAL_MERCHANT_ID" not in trans_src)
except Exception as e:
    r("F3", "Global merchant_id check", False, str(e))

# No silent state transitions (DB constraints)
try:
    clean_all()
    preload(100, "sweep_pass")
    wallet_db.expire_stale_tokens()
    ts = wallet_db.list_unspent_tokens(wallet_core._get_master_key("sweep_pass"))

    # Try to force-mark EXPIRED directly via DB
    import sqlite3
    conn = sqlite3.connect(wallet_db.DB_PATH)
    try:
        conn.execute("UPDATE tokens SET status='INVALID_STATUS' WHERE 1=1")
        conn.commit()
        r("F4", "DB enforces status CHECK constraint", False, "Invalid status accepted")
    except sqlite3.IntegrityError:
        r("F4", "DB enforces status CHECK constraint", True)
    finally:
        conn.rollback()
        conn.close()
except Exception as e:
    r("F4", "Silent state transition check", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY REPORT
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("REGRESSION SWEEP — SUMMARY")
print("="*60)
total = len(results)
passed = sum(1 for _, _, s, _ in results if s == "PASS")
failed = total - passed

for section, name, status, detail in results:
    prefix = "PASS" if status == "PASS" else "FAIL"
    safe_name = name.encode("ascii", errors="replace").decode("ascii")
    safe_det = detail.encode("ascii", errors="replace").decode("ascii")
    print(f"  [{prefix}] [{section}] {safe_name}" + (f" | {safe_det}" if safe_det else ""))

print(f"\nTotal: {total}  |  Passed: {passed}  |  Failed: {failed}")
sys.exit(0 if failed == 0 else 1)
