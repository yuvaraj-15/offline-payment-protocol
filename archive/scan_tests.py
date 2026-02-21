"""Scan test_suite.py for bare single-arg process_payment / verify_packet calls and patch them."""
import re, ast, sys

MERCHANT_MAP = {
    # maps packet creation merchantId to the identity used in LOCAL_MERCHANT_ID context
    # We scan for create_payment_packet calls to derive the correct merchant ID to inject.
}

with open('test_suite.py', 'r', encoding='utf-8') as f:
    content = f.read()
    lines = content.splitlines(keepends=True)

# Find every process_payment and verify_packet call that has exactly ONE arg (no second comma before close paren)
# Pattern: merch_core.process_payment(X) or merch_core.verify_packet(X)
# where X does not contain a comma at the top level (simple test: no ", " after the first arg before ")")
found = []
for i, line in enumerate(lines):
    stripped = line.strip()
    m1 = re.search(r'merch_core\.process_payment\(([^,)]+)\)', stripped)
    m2 = re.search(r'merch_core\.verify_packet\(([^,)]+)\)', stripped)
    if m1 or m2:
        found.append((i+1, line.rstrip(), 'process' if m1 else 'verify'))

for lineno, text, kind in found:
    print(f"  Line {lineno} [{kind}]: {text}")

print(f"\nTotal needing patch: {len(found)}")
