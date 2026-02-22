import os

from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore[import]
from cryptography.hazmat.primitives import serialization  # type: ignore[import]

from shared.paths import BANK_KEY_PATH, BANK_PUB_KEY_PATH  # type: ignore[import]

KEY_FILE = str(BANK_KEY_PATH)
PUB_KEY_FILE = str(BANK_PUB_KEY_PATH)

def load_or_generate_key():
    BANK_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
    else:
        print("Generating new Bank Key...")
        private_key = ec.generate_private_key(ec.SECP256R1())
        with open(KEY_FILE, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

    public_key = private_key.public_key()
    with open(PUB_KEY_FILE, "wb") as f:
        f.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    return private_key
