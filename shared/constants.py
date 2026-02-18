"""
Shared constants for the Offline Payment Protocol.
Strict adherence to MASTER_SPEC.md.
"""

# Curve: NIST P-256
CURVE_NAME = "SECP256R1"
HASH_ALG = "SHA256"

# Allowed Denominations (Section 5.2)
ALLOWED_DENOMINATIONS = {10, 50, 100, 200}

# Expiry Window (Section 8)
EXPIRY_SECONDS = 48 * 3600  # 48 hours

# Identifier (Section 5.1)
ISSUER_ID = "RuralBank01"
