import os
import sys
import uuid
import time
import dataclasses
from io import StringIO

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]
from shared.models import Token  # type: ignore[import]
from shared.crypto import sign_data, verify_signature, canonical_hash, derive_owner_hash  # type: ignore[import]
from shared.constants import ISSUER_ID, EXPIRY_SECONDS  # type: ignore[import]

LOG_PATH = os.path.join(os.path.dirname(__file__), "log_simulate_tampering.txt")

def run():
    lines = []

    def p(msg=""):
        print(msg)
        lines.append(msg)

    p("Scenario: Token Field Tampering")
    p("-" * 40)

    p("Step 1: Generating ephemeral bank key pair ...")
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    p("         done")

    p("Step 2: Issuing a valid signed token ...")
    now = int(time.time())
    buyer_id = "alice"
    token = Token(
        token_id=str(uuid.uuid4()),
        issuer_id=ISSUER_ID,
        owner_id_hash=derive_owner_hash(buyer_id),
        denomination=100,
        issue_timestamp=now,
        expiry_timestamp=now + EXPIRY_SECONDS,
        signature=""
    )
    token.signature = sign_data(private_key, canonical_hash(token))
    p(f"         token_id: {token.token_id}")
    p(f"         denomination: {token.denomination}")
    p("         done")

    p("Step 3: Verifying original token signature ...")
    original_hash = canonical_hash(token)
    original_valid = verify_signature(public_key, original_hash, token.signature)
    p(f"         Result: {'PASS' if original_valid else 'FAIL'}")

    p("Step 4: Tampering with denomination field (100 -> 500) ...")
    tampered = dataclasses.replace(token, denomination=500)
    p("         done")

    p("Step 5: Verifying tampered token signature ...")
    tampered_hash = canonical_hash(tampered)
    tampered_valid = verify_signature(public_key, tampered_hash, tampered.signature)
    p(f"         Result: {'PASS' if tampered_valid else 'FAIL (signature invalid as expected)'}")

    p()
    if not tampered_valid:
        p("Summary: Tampering simulation passed. Signature verification correctly rejected the modified token.")
    else:
        p("Summary: UNEXPECTED - tampered token passed verification. Protocol vulnerability detected.")

    with open(LOG_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    run()