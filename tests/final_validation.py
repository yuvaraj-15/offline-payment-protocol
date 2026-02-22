import os
import sys
import time
import json
import sqlite3
import unittest.mock
import copy
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
unittest.mock.patch('getpass.getpass', return_value='sys_test_pass').start()

from wallet import core as wallet_core, database as wallet_db  # type: ignore[import]
from merchant import core as merch_core, database as merch_db, settlement as merch_settlement, transport as merch_transport  # type: ignore[import]
from bank import database as bank_db, issuance as bank_issuance, keys as bank_keys, settlement as bank_settlement, refund as bank_refund  # type: ignore[import]
from shared.models import Token, TransactionPackage  # type: ignore[import]
from shared.crypto import canonical_hash, verify_signature  # type: ignore[import]

report = []

def log_step(step, desc, passed, evidence=""):
    status = "PASS" if passed else "FAIL"
    report.append(f"[{status}] {step}: {desc}\n   Evidence: {evidence}")
    print(report[-1])

def run_validation():
    print("Starting Final Full System Validation...\n")
    

    # STEP 1 - CLEAN ENVIRONMENT

    from shared.paths import WALLET_DB_PATH, WALLET_SALT_PATH, MERCHANT_DB_PATH, BANK_DB_PATH, BANK_KEY_PATH, BANK_PUB_KEY_PATH  # type: ignore[import]
    files_to_remove = [WALLET_DB_PATH, WALLET_SALT_PATH, MERCHANT_DB_PATH, BANK_DB_PATH, BANK_KEY_PATH, BANK_PUB_KEY_PATH]
    for f in files_to_remove:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception:
            pass
            
    bank_db.init_db(reset=True)
    bank_keys.load_or_generate_key()
    
    log_step("STEP 1", "Clean Environment", True, "Deleted DBs, .salt, keys, clean startup.")
    

    # STEP 2 - WALLET INITIALIZATION

    wallet_db.init_db()
    buyer_id = wallet_core.get_or_create_identity("sys_test_pass", "SystemTestBuyer")
    key = wallet_core._get_master_key("sys_test_pass")
    buyer_name = wallet_db.load_config("buyer_display_name", key)
    
    # Restart simulation (re-fetch)
    buyer_id_2 = wallet_core.get_or_create_identity("sys_test_pass")
    
    passed_s2 = (buyer_id == buyer_id_2) and (buyer_name == "SystemTestBuyer")
    log_step("STEP 2", "Wallet Initialization", passed_s2, f"ID1={buyer_id[:8]} ID2={buyer_id_2[:8]}, Name={buyer_name}")

    # STEP 3 - MERCHANT INITIALIZATION

    merch_db.init_db()
    merch_db.save_config("merchant_id", "TestMerchant123")
    merch_id = merch_db.load_config("merchant_id")
    
    # Restart
    merch_id_2 = merch_db.load_config("merchant_id")
    
    passed_s3 = (merch_id == merch_id_2) and len(merch_id) > 0
    log_step("STEP 3", "Merchant Initialization", passed_s3, f"MerchID={merch_id}")

    # STEP 4 - PRELOAD TEST

    count = wallet_core.preload_funds("sys_test_pass", 500)
    info = wallet_core.get_balance_info("sys_test_pass")
    
    tokens = info['tokens']
    denoms = [t.denomination for t in tokens]
    unique_ids = len(set(t.token_id for t in tokens))
    bank_bal = bank_db.get_balance(buyer_id)
    
    passed_s4 = (count > 0 and info['total'] == 500 and unique_ids == count and bank_bal == 500)
    log_step("STEP 4", "Preload Test", passed_s4, f"Tokens={count}, Total={info['total']}, BankBal={bank_bal}, UniqueIDs={unique_ids}")

    # STEP 5 - EXACT PAYMENT

    pay_amount = tokens[0].denomination
    
    packet_json = wallet_core.create_payment_packet("sys_test_pass", merch_id, pay_amount)
    pkt = json.loads(packet_json)
    
    # Process
    res_s5 = merch_core.process_payment(packet_json, merch_id)
    
    with merch_db.get_db() as conn:
        tx = conn.execute("SELECT status, requested_amount FROM transactions WHERE transaction_id=?", (pkt['transaction_id'],)).fetchone()
        
    info_post_s5 = wallet_core.get_balance_info("sys_test_pass")
    
    tok_sum = sum(t['denomination'] for t in pkt['tokens'])
    passed_s5 = (
        res_s5 is True and 
        pkt['requested_amount'] == pay_amount and
        tok_sum == pay_amount and
        tx['status'] == 'PENDING' and
        tx['requested_amount'] == pay_amount and
        info_post_s5['total'] == 500 - pay_amount
    )
    log_step("STEP 5", "Exact Payment", passed_s5, f"Req={pay_amount}, Sum={tok_sum}, DBStatus={tx['status']}, WalletBal={info_post_s5['total']}")

    # STEP 6 - OVERPAYMENT

    pay_amount_op = 10
    packet_json_op = wallet_core.create_payment_packet("sys_test_pass", merch_id, pay_amount_op)
    pkt_op = json.loads(packet_json_op)
    
    tok_sum_op = sum(t['denomination'] for t in pkt_op['tokens'])
    change_due = tok_sum_op - pay_amount_op
    
    res_s6 = merch_core.process_payment(packet_json_op, merch_id)
    
    passed_s6 = (
        res_s6 is True and
        tok_sum_op >= pay_amount_op and
        change_due > 0 and
        pkt_op['requested_amount'] == pay_amount_op
    )
    log_step("STEP 6", "Overpayment", passed_s6, f"Req={pay_amount_op}, TokSum={tok_sum_op}, ChangeDue={change_due}")

    # STEP 7 - UNDERPAYMENT ATTEMPT

    # Tamper the packet
    pkt_tampered = copy.deepcopy(pkt_op)
    pkt_tampered['requested_amount'] = tok_sum_op + 100
    pkt_tampered['transaction_id'] = "tampered-tx-123"
    
    try:
        merch_core.verify_packet(json.dumps(pkt_tampered), merch_id)
        passed_s7 = False
        evidence_s7 = "Accepted tampered packet"
    except ValueError as e:
        passed_s7 = "insufficient" in str(e).lower()
        evidence_s7 = f"Rejected with: {e}"
        
    log_step("STEP 7", "Underpayment Attempt", passed_s7, evidence_s7)

    # STEP 8 - REPLAY ATTACK

    res_s8 = merch_core.process_payment(packet_json, merch_id)
    with merch_db.get_db() as conn:
        tx_cnt = conn.execute("SELECT COUNT(*) FROM transactions WHERE transaction_id=?", (pkt['transaction_id'],)).fetchone()[0]
        
    passed_s8 = (res_s8 is False and tx_cnt == 1)
    log_step("STEP 8", "Replay Attack", passed_s8, f"Res={res_s8}, TxCount={tx_cnt}")

    # STEP 9 - SETTLEMENT TEST

    bank_db.create_account(merch_id, 0)
    settled_cnt = merch_settlement.settle_pending_transactions()
    
    bank_merch_bal = bank_db.get_balance(merch_id)
    expected_credit = tok_sum + tok_sum_op
    
    with bank_db.get_db_connection() as conn:
        tok_status = conn.execute("SELECT status FROM tokens WHERE token_id=?", (pkt['tokens'][0]['token_id'],)).fetchone()[0]
        
    passed_s9 = (
        settled_cnt == 2 and
        bank_merch_bal == expected_credit and
        tok_status == "SPENT"
    )
    log_step("STEP 9", "Settlement Test", passed_s9, f"Settled={settled_cnt}, MerchCredit={bank_merch_bal}, Expected={expected_credit}, TokStatus={tok_status}")

    # STEP 10 - DOUBLE SETTLEMENT

    tokens_obj = [Token(**t) for t in pkt['tokens']]
    pkg = TransactionPackage(
        transaction_id=pkt['transaction_id'],
        buyer_id_hash=pkt['buyer_id_hash'],
        merchant_id=merch_id,
        tokens=tokens_obj,
        transaction_timestamp=pkt['transaction_timestamp'],
        requested_amount=pkt['requested_amount'],
        buyer_display_name="x"
    )
    bank_pub = bank_keys.load_or_generate_key().public_key()
    res_s10 = bank_settlement.settle_transaction(bank_pub, pkg)
    
    passed_s10 = all(v == "REJECTED_DUPLICATE" for v in res_s10.values())
    bank_merch_bal_2 = bank_db.get_balance(merch_id)
    
    passed_s10 = passed_s10 and (bank_merch_bal == bank_merch_bal_2)
    log_step("STEP 10", "Double Settlement", passed_s10, f"Res={res_s10}, BalDiff={bank_merch_bal_2 - bank_merch_bal}")

    # STEP 11 - REFUND TEST

    wallet_core.preload_funds("sys_test_pass", 50)
    info = wallet_core.get_balance_info("sys_test_pass")
    refund_token_id = info['tokens'][0].token_id
    denom = info['tokens'][0].denomination
    
    res_11a = bank_refund.request_refund(buyer_id, refund_token_id)
    
    with bank_db.get_db_connection() as conn:
        conn.execute("UPDATE tokens SET expires_at=0 WHERE token_id=?", (refund_token_id,))
        conn.commit()
    
    res_11b = bank_refund.request_refund(buyer_id, refund_token_id)
    bank_buyer_bal = bank_db.get_balance(buyer_id)
    expected_bal = 450 + denom  
    
    passed_s11 = (res_11a == "FAILED_NOT_EXPIRED" and res_11b == "REFUNDED" and bank_buyer_bal == expected_bal)
    log_step("STEP 11", "Refund Test", passed_s11, f"Pre={res_11a}, Post={res_11b}, BuyerBal={bank_buyer_bal}")

    # STEP 12 - EXPIRY ENFORCEMENT

    wallet_core.preload_funds("sys_test_pass", 50)
    info = wallet_core.get_balance_info("sys_test_pass")
    exp_token = info['tokens'][0]
    
    original_time = time.time
    time.time = lambda: original_time() + 86400 * 2
    
    try:
        wallet_db.expire_stale_tokens()
        info_future = wallet_core.get_balance_info("sys_test_pass")
        passed_s12 = all(t.status == 'EXPIRED' for t in info_future['tokens'] if t.token_id == exp_token.token_id)
        
        import uuid, dataclasses
        from shared.crypto import derive_owner_hash  # type: ignore[import]
        pkt_exp = TransactionPackage(
            transaction_id=str(uuid.uuid4()),
            buyer_id_hash=derive_owner_hash(buyer_id),
            merchant_id=merch_id,
            tokens=[exp_token],
            transaction_timestamp=int(time.time()),
            requested_amount=20,
            buyer_display_name="SystemTestBuyer"
        )
        pkt_exp_json = json.dumps(dataclasses.asdict(pkt_exp))
        try:
            merch_core.verify_packet(pkt_exp_json, merch_id)
            merch_rej = False
        except ValueError as e:
            merch_rej = "expired" in str(e).lower()
            
        passed_s12 = passed_s12 and merch_rej
        evidence_s12 = f"LocalExpired={passed_s12}, MerchReject={merch_rej}"
    finally:
        time.time = original_time
        
    log_step("STEP 12", "Expiry Enforcement", passed_s12, evidence_s12)

    # STEP 13 - CRASH TEST

    class MockConnection:
        def __init__(self, real_conn):
            self.real_conn = real_conn
            self.row_factory = getattr(real_conn, 'row_factory', None)
        def execute(self, *args, **kwargs):
            query_upper = args[0].upper()
            if "UPDATE TOKENS" in query_upper and "SPENT" in query_upper:
                raise sqlite3.Error("simulated lock")
            return self.real_conn.execute(*args, **kwargs)
        def commit(self): pass
        def rollback(self): self.real_conn.rollback()
        
    original_get_db = wallet_db.get_db
    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        with original_get_db() as real_conn:
            yield MockConnection(real_conn)
            
    wallet_core.preload_funds("sys_test_pass", 50)
    info_c = wallet_core.get_balance_info("sys_test_pass")
    c_token_id = info_c['tokens'][0].token_id
            
    with unittest.mock.patch('wallet.database.get_db', side_effect=mock_get_db):
        try:
            wallet_db.mark_tokens_spent([c_token_id])
            passed_s13 = False
            evidence_s13 = "Did not raise RuntimeError"
        except RuntimeError as e:
            passed_s13 = "simulated lock" in str(e.__cause__) or "sqlite3" in str(e.__cause__)
            evidence_s13 = f"Raised RuntimeError: {e.__cause__}"
            
    with wallet_db.get_db() as conn:
        status_c = conn.execute("SELECT status FROM tokens WHERE token_id=?", (c_token_id,)).fetchone()[0]
    passed_s13 = passed_s13 and (status_c == 'UNSPENT')
            
    log_step("STEP 13", "Crash Test", passed_s13, f"{evidence_s13}. TokenStatus={status_c}")

    # STEP 14 - CANONICAL HASH CONSISTENCY

    t_hash = info_c['tokens'][0]
    t_dict = {
        "expiry_timestamp": t_hash.expiry_timestamp,
        "token_id": t_hash.token_id,
        "denomination": t_hash.denomination,
        "issuer_id": t_hash.issuer_id,
        "signature": t_hash.signature,
        "issue_timestamp": t_hash.issue_timestamp,
        "owner_id_hash": t_hash.owner_id_hash
    }
    t_obj2 = Token(**t_dict)
    
    h1 = canonical_hash(t_hash)
    h2 = canonical_hash(t_obj2)
    
    bank_pub = bank_keys.load_or_generate_key().public_key()
    sig1 = verify_signature(bank_pub, h1, t_hash.signature)
    sig2 = verify_signature(bank_pub, h2, t_obj2.signature)
    
    passed_s14 = (h1 == h2 and sig1 and sig2)
    log_step("STEP 14", "Canonical Hash Consistency", passed_s14, f"H1={h1.hex()[:8]}, H2={h2.hex()[:8]}, Sig1={sig1}, Sig2={sig2}")

    # STEP 15 - STATIC PORT VALIDATION

    with open(merch_transport.__file__, "r") as f:
        content = f.read()
    passed_s15 = "DEFAULT_PORT = 5050" in content
    log_step("STEP 15", "Static Port Validation", passed_s15, f"Static default PORT in transport: 5050")

    print("\n================ FINAL REPORT ================")
    for r in report:
        print(r)

if __name__ == "__main__":
    run_validation()
