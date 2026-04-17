"""Tests for system invariants and integrity."""
import unittest
import tempfile
import os
import time as _time
import random
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec  

from shared.models import TransactionPackage  
from shared.crypto import derive_owner_hash  
from bank.database import init_db, create_account, get_balance, get_db_connection  
from bank.issuance import issue_tokens  
from bank.settlement import settle_transaction  
from bank.refund import request_refund  

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.patcher = patch("bank.database.DB_PATH", self.db_path)
        self.patcher.start()
        init_db(reset=True)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.key.public_key()

    def tearDown(self):
        self.patcher.stop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _issued_value(self):
        with get_db_connection() as c:
            r = c.execute(
                "SELECT COALESCE(SUM(denomination),0) FROM tokens WHERE status='ISSUED'"
            ).fetchone()
            return r[0]

    def _total_balances(self):
        with get_db_connection() as c:
            r = c.execute("SELECT COALESCE(SUM(balance),0) FROM accounts").fetchone()
            return r[0]

    def _assert_no_negatives(self):
        with get_db_connection() as c:
            negs = c.execute(
                "SELECT user_id,balance FROM accounts WHERE balance<0"
            ).fetchall()
            self.assertEqual(len(negs), 0, f"Negatives: {negs}")


    def test_no_double_transition(self):
        create_account("Alice", 1000)
        create_account("M", 0)
        tokens = issue_tokens(self.key, "Alice", 200)
        t = tokens[0]
        tx = TransactionPackage("tx-1", derive_owner_hash("Alice"), "M",
                                [t], int(_time.time()), t.denomination, "Alice")
        r1 = settle_transaction(self.pub, tx)
        self.assertEqual(r1[t.token_id], "SETTLED")
        r2 = settle_transaction(self.pub, tx)
        self.assertNotEqual(r2[t.token_id], "SETTLED")
        future = int(_time.time()) + 200000
        with patch("bank.refund.time") as mt:
            mt.time.return_value = future
            self.assertNotEqual(request_refund("Alice", t.token_id), "REFUNDED")


    def test_no_negative_balances(self):
        create_account("Alice", 100)
        with self.assertRaises(ValueError):
            issue_tokens(self.key, "Alice", 200)
        self._assert_no_negatives()


    def test_money_invariant(self):
        create_account("Alice", 1000)
        create_account("M", 0)
        initial = self._total_balances() + self._issued_value()

        tokens = issue_tokens(self.key, "Alice", 350)
        self.assertEqual(initial, self._total_balances() + self._issued_value())

        tx = TransactionPackage("tx-1", derive_owner_hash("Alice"), "M",
                                tokens[:2], int(_time.time()),
                                sum(t.denomination for t in tokens[:2]), "Alice")
        settle_transaction(self.pub, tx)
        self.assertEqual(initial, self._total_balances() + self._issued_value())

        future = int(_time.time()) + 200000
        with patch("bank.refund.time") as mt:
            mt.time.return_value = future
            request_refund("Alice", tokens[2].token_id)
        self.assertEqual(initial, self._total_balances() + self._issued_value())


    def test_stress(self):
        rng = random.Random(42)
        create_account("Stress", 10000)
        create_account("SM", 0)
        initial = self._total_balances()

        all_tokens = []
        for _ in range(100):
            toks = issue_tokens(self.key, "Stress", 10)
            all_tokens.extend(toks)
        self.assertEqual(len(all_tokens), 100)

        rng.shuffle(all_tokens)
        future = int(_time.time()) + 200000

        for tok in all_tokens:
            if rng.choice(["settle", "refund"]) == "settle":
                tx = TransactionPackage(
                    f"tx-{tok.token_id[:8]}",
                    derive_owner_hash("Stress"), "SM",
                    [tok], int(_time.time()),
                    tok.denomination, "Stress"
                )
                r = settle_transaction(self.pub, tx)
                self.assertIn(r[tok.token_id],
                              ["SETTLED", "REJECTED_DUPLICATE", "REJECTED_REFUNDED"])
            else:
                with patch("bank.refund.time") as mt:
                    mt.time.return_value = future
                    s = request_refund("Stress", tok.token_id)
                self.assertIn(s, ["REFUNDED", "FAILED_SPENT", "FAILED_REFUNDED",
                                  "FAILED_NOT_EXPIRED"])

        self._assert_no_negatives()
        self.assertEqual(initial, self._total_balances() + self._issued_value())

        with get_db_connection() as c:
            for (st,) in c.execute("SELECT status FROM tokens").fetchall():
                self.assertIn(st, ["ISSUED", "SPENT", "REFUNDED"])

if __name__ == "__main__":
    unittest.main()
