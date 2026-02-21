"""
Merchant Transport Layer (Pure TCP / WiFi LAN).

Responsibilities:
1. Discover LAN IP via UDP routing trick.
2. Bind TCP socket to ("0.0.0.0", 0) — OS assigns port.
3. Generate QR code containing merchant_id, ip, port.
4. Display QR (GUI) or print to stdout (headless).
5. Accept incoming Wallet connections (blocking, no timeout).
6. Read single JSON packet framed by newline.
7. Pass JSON to merchant.core for verification.
8. Send ACK_SUCCESS\\n or ACK_REJECT\\n.
9. Close client socket. Loop.

Protocol isolation: transport passes JSON string unchanged to core.
"""
import sys
import json
import socket
import logging
import threading
import cv2  # type: ignore[import]
import numpy as np  # type: ignore[import]
import qrcode  # type: ignore[import]
from merchant import core  # type: ignore[import]
from merchant.database import init_db  # type: ignore[import]

logging.basicConfig(level=logging.INFO, format='[TCP-Transport] %(message)s')
logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0
BUFFER_SIZE = 4096


def get_lan_ip() -> str:
    """Return the machine's LAN IP by probing the default route.

    Uses a non-transmitting UDP connect to determine the outbound interface.
    Raises RuntimeError if no routable LAN IP is found (e.g. no WiFi).

    When env var MERCHANT_TEST_LOOPBACK=1 is set (CI / headless tests),
    returns 127.0.0.1 to allow local loopback testing without a real LAN.
    """
    import os
    if os.environ.get("MERCHANT_TEST_LOOPBACK") == "1":
        logger.info("MERCHANT_TEST_LOOPBACK=1 — using 127.0.0.1 for testing")
        return "127.0.0.1"

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not transmit — just populates the kernel routing info
        s.connect(("8.8.8.8", 80))
        ip: str = s.getsockname()[0]
    finally:
        s.close()

    if ip.startswith("127."):
        raise RuntimeError(
            f"No LAN IP detected (got {ip}). "
            "Ensure the machine is connected to a WiFi/LAN network."
        )
    return ip


def generate_qr_image(data_str: str):  # type: ignore[return]
    """Generate QR code as a numpy array (BGR) for OpenCV display."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    pil_image = img.convert('RGB')
    open_cv_image = np.array(pil_image)
    return open_cv_image[:, :, ::-1].copy()  # type: ignore[index]


def handle_client(client_sock: socket.socket, client_addr: tuple, merchant_id: str) -> None:
    """Handle a single incoming Wallet connection (single-shot protocol)."""
    try:
        logger.info(f"Connection accepted from {client_addr}")
        client_sock.settimeout(TIMEOUT_SECONDS)

        # Accumulate bytes until first newline
        buffer = b""
        while b'\n' not in buffer:
            try:
                chunk = client_sock.recv(BUFFER_SIZE)
            except socket.timeout:
                logger.error("Client timed out before sending complete packet")
                return
            if not chunk:
                logger.error("Client disconnected before complete packet received")
                return
            buffer += chunk

        # Extract exactly one frame; ignore any trailing bytes
        payload_bytes = buffer.split(b'\n', 1)[0]

        try:
            json_str = payload_bytes.decode('utf-8')
        except UnicodeDecodeError as e:
            logger.error(f"Invalid UTF-8 in payload: {e}")
            client_sock.sendall(b"ACK_REJECT\n")
            return

        logger.info(f"Received payload ({len(json_str)} chars) — forwarding to core")

        try:
            success = core.process_payment(json_str, merchant_id)
            ack = b"ACK_SUCCESS\n" if success else b"ACK_REJECT\n"
        except Exception as e:
            logger.error(f"Core processing error: {e}")
            ack = b"ACK_REJECT\n"

        client_sock.sendall(ack)
        logger.info(f"Sent: {ack.strip().decode()}")

    except Exception as e:
        logger.error(f"Unexpected error in handle_client: {e}")
    finally:
        try:
            client_sock.close()
        except OSError as e:
            logger.debug(f"Socket close error: {e}")
        logger.info(f"Client connection closed ({client_addr})")


def start_server(merchant_id: str, headless: bool = False) -> None:
    """Bind TCP server, generate QR, and accept Wallet connections.

    Args:
        merchant_id: Merchant identifier embedded in QR payload.
        headless:    If True, skip OpenCV window; log QR data to stdout only.
    """
    # --- Discover LAN IP (raises RuntimeError if not on LAN) ---
    lan_ip = get_lan_ip()

    DEFAULT_PORT = 5050
    # --- Bind TCP server socket ---
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind(("0.0.0.0", DEFAULT_PORT))
    except OSError:
        logger.error(f"Port {DEFAULT_PORT} is already in use. Aborting server start.")
        sys.exit(1)
        
    server_sock.listen(1)
    # Server accept() has NO timeout — blocks indefinitely.

    port: int = DEFAULT_PORT
    logger.info(f"TCP server bound — IP: {lan_ip}  Port: {port}")

    # --- Build QR payload ---
    qr_payload = json.dumps({
        "merchant_id": merchant_id,
        "ip": lan_ip,
        "port": port,
    })
    logger.info(f"QR Data: {qr_payload}")

    # --- Accept loop (runs in background thread for GUI mode) ---
    def server_loop() -> None:
        logger.info("Listening for Wallet connections...")
        while True:
            try:
                client_sock, client_addr = server_sock.accept()
                t = threading.Thread(
                    target=handle_client,
                    args=(client_sock, client_addr, merchant_id),
                    daemon=True,
                )
                t.start()
            except OSError:
                # Socket was closed by 'q' or Ctrl+C
                logger.info("Server socket closed, stopping accept loop.")
                break
            except Exception as e:
                logger.error(f"Accept error: {e}")
                # Brief pause to avoid tight error loops
                import time
                time.sleep(0.5)

    if headless:
        logger.info("Headless mode — serving on main thread (Ctrl-C to stop)")
        server_loop()  # blocks
    else:
        # GUI mode: show QR window; accept loop in daemon thread
        qr_img = generate_qr_image(qr_payload)
        t = threading.Thread(target=server_loop, daemon=True)
        t.start()
        logger.info("Press 'q' in the QR window to stop.")
        while True:
            cv2.imshow(f"Merchant QR — {merchant_id}", qr_img)
            if cv2.waitKey(100) & 0xFF == ord('q'):
                break
        server_sock.close()
        cv2.destroyAllWindows()
        # Return instead of killing the entire process
        return


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m merchant.transport <merchant_id> [--headless]")
        sys.exit(1)
    init_db()
    start_server(sys.argv[1], headless="--headless" in sys.argv)
