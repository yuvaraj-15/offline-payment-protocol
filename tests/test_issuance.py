"""Tests for bank/issuance.py."""
import unittest
import tempfile
import os
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec  

from shared.constants import EXPIRY_SECONDS  
from bank.database import init_db, create_account, get_balance  
from bank.issuance import issue_tokens  

class TestIssuance(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.patcher = patch("bank.database.DB_PATH", self.db_path)
        self.patcher.start()
        init_db(reset=True)
        self.key = ec.generate_private_key(ec.SECP256R1())
        create_account("Alice", 1000)

    def tearDown(self):
        self.patcher.stop()
        os.close(self.db_fd)
        os.unlink(self.db_path)


    def test_reject_zero(self):
        with self.assertRaises(ValueError):
            issue_tokens(self.key, "Alice", 0)

    def test_reject_negative(self):
        with self.assertRaises(ValueError):
            issue_tokens(self.key, "Alice", -10)


    def test_reject_non_multiple_of_10(self):
        with self.assertRaises(ValueError):
            issue_tokens(self.key, "Alice", 15)

    def test_reject_insufficient_balance(self):
        with self.assertRaises(ValueError):
            issue_tokens(self.key, "Alice", 2000)


    def test_denomination_breakdown(self):
        tokens = issue_tokens(self.key, "Alice", 350)
        denoms = sorted([t.denomination for t in tokens], reverse=True)
        self.assertEqual(denoms, [200, 100, 50])


    def test_expiry_correctness(self):
        tokens = issue_tokens(self.key, "Alice", 100)
        for t in tokens:
            self.assertEqual(t.expiry_timestamp, t.issue_timestamp + EXPIRY_SECONDS)


    def test_balance_invariant(self):
        before = get_balance("Alice")
        tokens = issue_tokens(self.key, "Alice", 350)
        after = get_balance("Alice")
        self.assertEqual(before, after + sum(t.denomination for t in tokens))

if __name__ == "__main__":
    unittest.main()
