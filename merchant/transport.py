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
    
    import os
    if os.environ.get("MERCHANT_TEST_LOOPBACK") == "1":
        logger.info("MERCHANT_TEST_LOOPBACK=1 — using 127.0.0.1 for testing")
        return "127.0.0.1"

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
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
    try:
        logger.info(f"Connection accepted from {client_addr}")
        client_sock.settimeout(TIMEOUT_SECONDS)

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
    lan_ip = get_lan_ip()
    DEFAULT_PORT = 5050
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind(("0.0.0.0", DEFAULT_PORT))
    except OSError:
        logger.error(f"Port {DEFAULT_PORT} is already in use. Aborting server start.")
        sys.exit(1)
        
    server_sock.listen(1)

    port: int = DEFAULT_PORT
    logger.info(f"TCP server bound — IP: {lan_ip}  Port: {port}")

    qr_payload = json.dumps({
        "merchant_id": merchant_id,
        "ip": lan_ip,
        "port": port,
    })
    logger.info(f"QR Data: {qr_payload}")

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
                # Socket closed by 'q'
                logger.info("Server socket closed, stopping accept loop.")
                break
            except Exception as e:
                logger.error(f"Accept error: {e}")
                import time
                time.sleep(0.5)

    if headless:
        logger.info("Headless mode — serving on main thread (Ctrl-C to stop)")
        server_loop()
    else:
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
        return

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m merchant.transport <merchant_id> [--headless]")
        sys.exit(1)
    init_db()
    start_server(sys.argv[1], headless="--headless" in sys.argv)
