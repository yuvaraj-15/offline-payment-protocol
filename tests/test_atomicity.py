"""Tests for atomicity and race condition prevention."""
import unittest
import tempfile
import os
import time as _time
import threading
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]

from shared.models import TransactionPackage  # type: ignore[import]
from shared.crypto import derive_owner_hash  # type: ignore[import]
from bank.database import init_db, create_account  # type: ignore[import]
from bank.issuance import issue_tokens  # type: ignore[import]
from bank.settlement import settle_transaction  # type: ignore[import]
from bank.refund import request_refund  # type: ignore[import]


class TestAtomicity(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.patcher = patch("bank.database.DB_PATH", self.db_path)
        self.patcher.start()
        init_db(reset=True)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.key.public_key()
        create_account("Alice", 1000)
        create_account("Merchant", 0)
        self.tokens = issue_tokens(self.key, "Alice", 100)

    def tearDown(self):
        self.patcher.stop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _tx(self, tokens):
        return TransactionPackage(
            transaction_id="tx-race",
            buyer_id_hash=derive_owner_hash("Alice"),
            merchant_id="Merchant",
            tokens=tokens,
            transaction_timestamp=int(_time.time()),
            requested_amount=sum(t.denomination for t in tokens),
            buyer_display_name="Alice"
        )

    # A — concurrent settle vs refund
    def test_concurrent_settle_and_refund(self):
        token = self.tokens[0]
        tx = self._tx([token])
        future = int(_time.time()) + 200000
        settle_result = {}
        refund_result = [None]

        def do_settle():
            r = settle_transaction(self.pub, tx)
            settle_result.update(r)

        def do_refund():
            with patch("bank.refund.time") as mt:
                mt.time.return_value = future
                refund_result[0] = request_refund("Alice", token.token_id)

        t1 = threading.Thread(target=do_settle)
        t2 = threading.Thread(target=do_refund)
        t1.start(); t2.start()
        t1.join(); t2.join()

        settled = settle_result.get(token.token_id) == "SETTLED"
        refunded = refund_result[0] == "REFUNDED"
        success_count = int(settled) + int(refunded)
        self.assertEqual(success_count, 1,
                         f"Exactly one must succeed: settle={settled}, refund={refunded}")

    # B — double settlement race
    def test_double_settlement_race(self):
        token = self.tokens[0]
        tx = self._tx([token])
        results = [None, None]

        def do_settle(idx):
            r = settle_transaction(self.pub, tx)
            results[idx] = r.get(token.token_id)

        t1 = threading.Thread(target=do_settle, args=(0,))
        t2 = threading.Thread(target=do_settle, args=(1,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        self.assertEqual(sum(1 for r in results if r == "SETTLED"), 1,
                         f"Expected exactly 1 SETTLED: {results}")

    # C — rowcount guard sequential
    def test_rowcount_guard(self):
        token = self.tokens[0]
        tx = self._tx([token])
        r1 = settle_transaction(self.pub, tx)
        self.assertEqual(r1[token.token_id], "SETTLED")
        r2 = settle_transaction(self.pub, tx)
        self.assertEqual(r2[token.token_id], "REJECTED_DUPLICATE")


if __name__ == "__main__":
    unittest.main()
