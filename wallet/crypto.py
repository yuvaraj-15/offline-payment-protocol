import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore[import]
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # type: ignore[import]
from cryptography.hazmat.primitives import hashes  # type: ignore[import]

SALT_SIZE = 16
IV_SIZE = 12  
KEY_SIZE = 32  # 256 bits
ITERATIONS = 100_000

def derive_key(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    if salt is None:
        salt = os.urandom(SALT_SIZE)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=ITERATIONS,
    )
    key = kdf.derive(password.encode("utf-8"))
    return key, salt

def encrypt_blob(key: bytes, plaintext: bytes) -> bytes:
    #Encrypt data using AES-256-GCM.
    #Format: IV (12) + Ciphertext + Tag (16)
    iv = os.urandom(IV_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    return iv + ciphertext

def decrypt_blob(key: bytes, blob: bytes) -> bytes:
    #Decrypt data using AES-256-GCM.
    #Expects blob = IV (12) + Ciphertext_with_Tag.
    if len(blob) < IV_SIZE + 16:
        raise ValueError("Blob too short")
    
    iv = blob[:IV_SIZE]  # type: ignore[index]
    ciphertext = blob[IV_SIZE:]  # type: ignore[index]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext, None)
