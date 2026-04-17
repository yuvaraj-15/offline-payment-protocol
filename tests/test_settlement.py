"""Tests for bank/settlement.py."""
import unittest
import tempfile
import os
import time as _time
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec  

from shared.models import TransactionPackage  
from shared.crypto import derive_owner_hash  
from bank.database import init_db, create_account, get_balance  
from bank.issuance import issue_tokens  
from bank.settlement import settle_transaction  
from bank.refund import request_refund  

class TestSettlement(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.patcher = patch("bank.database.DB_PATH", self.db_path)
        self.patcher.start()
        init_db(reset=True)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.key.public_key()
        create_account("Alice", 1000)
        create_account("Merchant", 0)
        self.tokens = issue_tokens(self.key, "Alice", 200)

    def tearDown(self):
        self.patcher.stop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _tx(self, tokens):
        return TransactionPackage(
            transaction_id="tx-test",
            buyer_id_hash=derive_owner_hash("Alice"),
            merchant_id="Merchant",
            tokens=tokens,
            transaction_timestamp=int(_time.time()),
            requested_amount=sum(t.denomination for t in tokens),
            buyer_display_name="Alice"
        )


    def test_valid_settlement(self):
        r = settle_transaction(self.pub, self._tx(self.tokens))
        for s in r.values():
            self.assertEqual(s, "SETTLED")


    def test_duplicate_settlement(self):
        settle_transaction(self.pub, self._tx(self.tokens))
        r2 = settle_transaction(self.pub, self._tx(self.tokens))
        for s in r2.values():
            self.assertEqual(s, "REJECTED_DUPLICATE")


    def test_settlement_after_expiry(self):
        past = 1000000
        with patch("bank.issuance.time") as mt:
            mt.time.return_value = past
            expired = issue_tokens(self.key, "Alice", 100)
        self.assertLess(expired[0].expiry_timestamp, int(_time.time()))
        r = settle_transaction(self.pub, self._tx(expired))
        for s in r.values():
            self.assertEqual(s, "SETTLED")


    def test_merchant_balance(self):
        settle_transaction(self.pub, self._tx(self.tokens))
        expected = sum(t.denomination for t in self.tokens)
        self.assertEqual(get_balance("Merchant"), expected)


    def test_cannot_settle_refunded(self):
        t = self.tokens[0]
        future = int(_time.time()) + 200000
        with patch("bank.refund.time") as mt:
            mt.time.return_value = future
            self.assertEqual(request_refund("Alice", t.token_id), "REFUNDED")
        r = settle_transaction(self.pub, self._tx([t]))
        self.assertEqual(r[t.token_id], "REJECTED_REFUNDED")


    def test_cannot_settle_spent(self):
        settle_transaction(self.pub, self._tx(self.tokens))
        r2 = settle_transaction(self.pub, self._tx(self.tokens))
        for s in r2.values():
            self.assertEqual(s, "REJECTED_DUPLICATE")

if __name__ == "__main__":
    unittest.main()
