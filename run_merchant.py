"""
Role A - Merchant Runner.

Starts the Merchant TCP Transport Server.
Usage: python run_merchant.py <merchant_id> [--headless]
"""
import sys
import os

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from merchant.transport import start_server  # type: ignore[import]
from merchant.database import init_db  # type: ignore[import]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_merchant.py <merchant_id> [--headless]")
        print("Example: python run_merchant.py Merchant01")
        sys.exit(1)

    merchant_id = sys.argv[1]
    headless = "--headless" in sys.argv

    print(f"--- Starting Merchant TCP Server: {merchant_id} ---")

    init_db()

    try:
        start_server(merchant_id, headless=headless)
    except RuntimeError as e:
        print(f"\n[FATAL] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nServer stopped.")
