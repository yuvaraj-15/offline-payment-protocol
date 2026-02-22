import hashlib
from cryptography.hazmat.primitives import hashes  # type: ignore[import]
from cryptography.hazmat.primitives.asymmetric import ec, utils  # type: ignore[import]
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # type: ignore[import]
from cryptography.exceptions import InvalidSignature  # type: ignore[import]

from shared.models import Token  # type: ignore[import]

def canonical_hash(token: Token) -> bytes:
    raw_string = (
        f"{token.token_id}"
        f"{token.issuer_id}"
        f"{token.owner_id_hash}"
        f"{token.denomination}"
        f"{token.issue_timestamp}"
        f"{token.expiry_timestamp}"
    )

    return hashlib.sha256(raw_string.encode('utf-8')).digest()

def derive_owner_hash(buyer_id: str) -> str:
    return hashlib.sha256(buyer_id.encode('utf-8')).hexdigest()

def sign_data(private_key: ec.EllipticCurvePrivateKey, data_hash: bytes) -> str:
    signature = private_key.sign(
        data_hash,
        ec.ECDSA(utils.Prehashed(hashes.SHA256()))
    )
    return signature.hex()

def verify_signature(public_key: ec.EllipticCurvePublicKey, data_hash: bytes, signature_hex: str) -> bool:
    try:
        signature_bytes = bytes.fromhex(signature_hex)
        public_key.verify(
            signature_bytes,
            data_hash,
            ec.ECDSA(utils.Prehashed(hashes.SHA256()))
        )
        return True
    except (InvalidSignature, ValueError):
        return False
