"""
Fix all bare merch_core.process_payment(X) and merch_core.verify_packet(X) calls
by injecting the correct merchant_id as a second argument.

The merchant_id to inject is derived from the nearest preceding
wallet_core.create_payment_packet(... "MERCH_ID" ...) call in the same function.
"""
import re

with open('test_suite.py', 'r', encoding='utf-8') as f:
    source = f.read()
    lines = source.splitlines(keepends=True)

# Build a mapping: for each process_payment / verify_packet call that has no second arg,
# scan upward from that line to find the most recent create_payment_packet call and
# extract the merchant_id from it.
PACKET_RE = re.compile(r'create_payment_packet\([^,]+,\s*["\']([^"\']+)["\']')
PROC_RE   = re.compile(r'(merch_core\.(process_payment|verify_packet)\([^,)]+)\)')

new_lines = list(lines)

for i in range(len(lines) - 1, -1, -1):
    line = new_lines[i]
    # Only target bare single-arg calls
    m = PROC_RE.search(line)
    if not m:
        continue

    # Make sure it already doesn't have a second arg (no additional comma + content)
    call_start = m.start(1)
    remainder = m.group(0)
    inner = remainder[remainder.index('(') + 1 : -1]  # type: ignore[index]
    # If there's already a comma it's already patched
    if ',' in inner:
        continue

    # Scan upward for the most recent create_payment_packet with merchant arg
    merchant_id = None
    for j in range(i, max(i - 80, -1), -1):
        pm = PACKET_RE.search(new_lines[j])  # type: ignore
        if pm:
            merchant_id = pm.group(1)
            break

    if merchant_id is None:
        print(f"  WARNING: could not find merchant_id for line {i+1}: {line.rstrip()}")
        continue

    # Patch the line
    patched = PROC_RE.sub(
        lambda m: f"{m.group(1)}, \"{merchant_id}\")",
        line
    )
    print(f"  Line {i+1}: adding merchant_id={merchant_id!r}")
    new_lines[i] = patched

with open('test_suite.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("\nDone. test_suite.py patched.")
