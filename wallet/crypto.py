import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  
from cryptography.hazmat.primitives import hashes  

SALT_SIZE = 16
IV_SIZE = 12  
KEY_SIZE = 32  
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
    iv = os.urandom(IV_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    return iv + ciphertext

def decrypt_blob(key: bytes, blob: bytes) -> bytes:
    if len(blob) < IV_SIZE + 16:
        raise ValueError("Blob too short")
    
    iv = blob[:IV_SIZE]
    ciphertext = blob[IV_SIZE:]  
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext, None)
