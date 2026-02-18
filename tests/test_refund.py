"""Tests for bank/refund.py."""
import unittest
import tempfile
import os
import time as _time
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]

from shared.models import TransactionPackage  # type: ignore[import]
from shared.crypto import derive_owner_hash  # type: ignore[import]
from bank.database import init_db, create_account, get_balance  # type: ignore[import]
from bank.issuance import issue_tokens  # type: ignore[import]
from bank.settlement import settle_transaction  # type: ignore[import]
from bank.refund import request_refund  # type: ignore[import]


class TestRefund(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.patcher = patch("bank.database.DB_PATH", self.db_path)
        self.patcher.start()
        init_db(reset=True)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.key.public_key()
        create_account("Alice", 1000)
        create_account("Merchant", 0)
        self.tokens = issue_tokens(self.key, "Alice", 350)
        self.future = int(_time.time()) + 200000

    def tearDown(self):
        self.patcher.stop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    # A
    def test_refund_before_expiry_fails(self):
        self.assertEqual(
            request_refund("Alice", self.tokens[0].token_id), "FAILED_NOT_EXPIRED"
        )

    # B
    def test_refund_after_expiry_succeeds(self):
        with patch("bank.refund.time") as mt:
            mt.time.return_value = self.future
            self.assertEqual(
                request_refund("Alice", self.tokens[0].token_id), "REFUNDED"
            )

    # C
    def test_refund_spent_fails(self):
        tx = TransactionPackage(
            transaction_id="tx-1",
            buyer_id_hash=derive_owner_hash("Alice"),
            merchant_id="Merchant",
            tokens=[self.tokens[0]],
            transaction_timestamp=int(_time.time()),
        )
        settle_transaction(self.pub, tx)
        with patch("bank.refund.time") as mt:
            mt.time.return_value = self.future
            self.assertEqual(
                request_refund("Alice", self.tokens[0].token_id), "FAILED_SPENT"
            )

    # D
    def test_refund_already_refunded_fails(self):
        with patch("bank.refund.time") as mt:
            mt.time.return_value = self.future
            request_refund("Alice", self.tokens[0].token_id)
            self.assertEqual(
                request_refund("Alice", self.tokens[0].token_id), "FAILED_REFUNDED"
            )

    # E
    def test_buyer_balance_updates(self):
        before = get_balance("Alice")
        denom = self.tokens[0].denomination
        with patch("bank.refund.time") as mt:
            mt.time.return_value = self.future
            request_refund("Alice", self.tokens[0].token_id)
        self.assertEqual(get_balance("Alice"), before + denom)


if __name__ == "__main__":
    unittest.main()
