"""Tests for shared/crypto.py — canonical hashing and signature integrity."""
import unittest
import hashlib
from copy import deepcopy

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]

from shared.models import Token  # type: ignore[import]
from shared.crypto import canonical_hash, sign_data, verify_signature  # type: ignore[import]


def _fixed_token():
    return Token(
        token_id="test-token-001",
        issuer_id="RuralBank01",
        owner_id_hash="abc123hash",
        denomination=100,
        issue_timestamp=1700000000,
        expiry_timestamp=1700172800,
        signature="",
    )


# Pre-compute expected digest
_RAW = "test-token-001RuralBank01abc123hash10017000000001700172800"
_EXPECTED_HEX = hashlib.sha256(_RAW.encode("utf-8")).hexdigest()


class TestCanonicalHashDeterminism(unittest.TestCase):
    """A. Canonical Hash Determinism."""

    def test_identical_digest(self):
        t = _fixed_token()
        self.assertEqual(canonical_hash(t), canonical_hash(t))

    def test_expected_hex_digest(self):
        t = _fixed_token()
        self.assertEqual(canonical_hash(t).hex(), _EXPECTED_HEX)


class TestFieldMutationProtection(unittest.TestCase):
    """B. Field Mutation Protection — modifying any field invalidates signature."""

    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.key.public_key()
        self.token = _fixed_token()
        h = canonical_hash(self.token)
        self.token.signature = sign_data(self.key, h)

    def _assert_mutation_fails(self, field, value):
        t = deepcopy(self.token)
        setattr(t, field, value)
        self.assertFalse(verify_signature(self.pub, canonical_hash(t), t.signature))

    def test_mutate_token_id(self):
        self._assert_mutation_fails("token_id", "CHANGED")

    def test_mutate_issuer_id(self):
        self._assert_mutation_fails("issuer_id", "CHANGED")

    def test_mutate_owner_id_hash(self):
        self._assert_mutation_fails("owner_id_hash", "CHANGED")

    def test_mutate_denomination(self):
        self._assert_mutation_fails("denomination", 999)

    def test_mutate_issue_timestamp(self):
        self._assert_mutation_fails("issue_timestamp", 1)

    def test_mutate_expiry_timestamp(self):
        self._assert_mutation_fails("expiry_timestamp", 1)


class TestSignatureFieldExclusion(unittest.TestCase):
    """C. Changing signature field must NOT change canonical_hash."""

    def test_signature_excluded(self):
        t1 = _fixed_token(); t1.signature = "aabb"
        t2 = _fixed_token(); t2.signature = "ccdd"
        self.assertEqual(canonical_hash(t1), canonical_hash(t2))


class TestBitFlip(unittest.TestCase):
    """D. Flipping 1 bit in signature must fail verification."""

    def test_bit_flip(self):
        key = ec.generate_private_key(ec.SECP256R1())
        t = _fixed_token()
        h = canonical_hash(t)
        sig = sign_data(key, h)
        flipped = bytearray(bytes.fromhex(sig))
        flipped[0] ^= 0x01
        self.assertFalse(verify_signature(key.public_key(), h, flipped.hex()))


if __name__ == "__main__":
    unittest.main()
