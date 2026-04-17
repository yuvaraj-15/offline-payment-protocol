import sys
import json
import socket
import logging
import threading
import cv2
import numpy as np
import qrcode

from merchant import core
from merchant.database import init_db

logging.basicConfig(level=logging.INFO, format='[TCP-Transport] %(message)s')
logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
BUFFER_SIZE = 4096


def get_lan_ip():

    import os

    if os.environ.get("MERCHANT_TEST_LOOPBACK") == "1":
        logger.info("MERCHANT_TEST_LOOPBACK=1 — using 127.0.0.1")
        return "127.0.0.1"

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()

    return ip


def generate_qr_image(data_str):

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )

    qr.add_data(data_str)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    pil_image = img.convert("RGB")
    open_cv_image = np.array(pil_image)

    return open_cv_image[:, :, ::-1].copy()


def build_qr_payload(merchant_id):

    lan_ip = get_lan_ip()
    port = 6000

    payload = json.dumps({
        "merchant_id": merchant_id,
        "ip": lan_ip,
        "port": port,
    })

    qr_img = generate_qr_image(payload)

    return payload, qr_img, lan_ip, port


def handle_client(client_sock, client_addr, merchant_id, notify_callback=None):

    try:

        client_sock.settimeout(TIMEOUT_SECONDS)

        buffer = b""

        while b'\n' not in buffer:

            chunk = client_sock.recv(BUFFER_SIZE)

            if not chunk:
                return

            buffer += chunk

        payload_bytes = buffer.split(b'\n', 1)[0]

        json_str = payload_bytes.decode("utf-8")

        try:
            success = core.process_payment(json_str, merchant_id)

            if success and notify_callback:
                try:
                    notify_callback(json_str)
                except Exception:
                    pass

            ack = b"ACK_SUCCESS\n" if success else b"ACK_REJECT\n"

        except Exception:
            ack = b"ACK_REJECT\n"

        client_sock.sendall(ack)

    finally:

        try:
            client_sock.close()
        except:
            pass


def server_loop(server_sock, merchant_id, notify_callback=None):

    while True:

        try:

            client_sock, client_addr = server_sock.accept()

            t = threading.Thread(
                target=handle_client,
                args=(client_sock, client_addr, merchant_id, notify_callback),
                daemon=True,
            )

            t.start()

        except OSError:
            break


def start_server(merchant_id, headless=False):

    payload, qr_img, lan_ip, port = build_qr_payload(merchant_id)

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    server_sock.bind(("0.0.0.0", port))

    server_sock.listen(5)

    logger.info(f"TCP server bound — IP: {lan_ip} Port: {port}")

    thread = threading.Thread(
        target=server_loop,
        args=(server_sock, merchant_id),
        daemon=True
    )

    thread.start()

    if headless:
        return qr_img, server_sock

    while True:

        cv2.imshow(f"Merchant QR — {merchant_id}", qr_img)

        if cv2.waitKey(100) & 0xFF == ord("q"):
            break

    server_sock.close()
    cv2.destroyAllWindows()


def start_server_gui(merchant_id, notify_callback=None):

    qr_img, server_sock = start_server(merchant_id, headless=True)

    return qr_img, server_sock


if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python -m merchant.transport <merchant_id>")
        sys.exit(1)

    init_db()

    start_server(sys.argv[1])