import os
import sys
import uvicorn

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


if __name__ == "__main__":
    host = os.getenv("BANK_HOST", "127.0.0.1")
    port = int(os.getenv("BANK_PORT", "8000"))
    uvicorn.run("bank.http_server:app", host=host, port=port, log_level="info")
