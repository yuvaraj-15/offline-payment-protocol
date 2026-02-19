"""
Wallet Transport Layer (Pure TCP / WiFi LAN).

Responsibilities:
1. Scan QR code via webcam (cv2 + pyzbar).
2. Parse ip + port from QR JSON payload.
3. Connect to Merchant via TCP.
4. Send payment packet as compact JSON + newline.
5. Wait for ACK (5-second timeout).
6. Return True on ACK_SUCCESS, False otherwise.

Protocol isolation: receives JSON string from wallet.core, sends unchanged.
"""
import json
import socket
import logging
import cv2  # type: ignore[import]
from pyzbar.pyzbar import decode as pyzbar_decode  # type: ignore[import]

logging.basicConfig(level=logging.INFO, format='[TCP-Transport] %(message)s')
logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0
BUFFER_SIZE = 4096


def scan_qr() -> tuple[str, str, int]:
    """Open webcam and scan for Merchant QR code.

    Returns:
        (merchant_id, ip, port) extracted from QR JSON.

    Raises:
        RuntimeError: If camera cannot be opened or no QR found within
                      camera session (user presses 'q').
    """
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("[TCP-Transport] Cannot open camera (device 0)")

    logger.info("Camera opened — point at Merchant QR code. Press 'q' to cancel.")
    found_data: dict | None = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                raise RuntimeError("[TCP-Transport] Camera read failure")

            decoded_objects = pyzbar_decode(frame)
            for obj in decoded_objects:
                try:
                    data = json.loads(obj.data.decode('utf-8'))
                    if all(k in data for k in ("merchant_id", "ip", "port")):
                        # Highlight QR bounding box
                        pts = obj.polygon
                        if len(pts) == 4:
                            pts_list = [(p.x, p.y) for p in pts]
                            import numpy as np  # type: ignore[import]
                            pts_np = np.array(pts_list, np.int32)
                            pts_np = pts_np.reshape((-1, 1, 2))
                            cv2.polylines(frame, [pts_np], True, (0, 255, 0), 3)
                        found_data = data
                except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
                    pass

            cv2.imshow("Wallet — Scan Merchant QR (q to cancel)", frame)

            if found_data:
                # Brief pause to let user see the green highlight
                cv2.waitKey(500)
                break

            if cv2.waitKey(1) & 0xFF == ord('q'):
                raise RuntimeError("[TCP-Transport] QR scan cancelled by user")
    finally:
        cap.release()
        cv2.destroyAllWindows()

    assert found_data is not None, "scan_qr: exited loop without data"
    merchant_id: str = found_data["merchant_id"]  # type: ignore[index]
    ip: str = found_data["ip"]  # type: ignore[index]
    port: int = int(found_data["port"])  # type: ignore[index,arg-type]
    logger.info(f"QR scanned — merchant: {merchant_id}  ip: {ip}  port: {port}")
    return merchant_id, ip, port  # type: ignore[return-value]


def send_payment(packet_json: str, ip: str, port: int) -> bool:
    """Connect to Merchant via TCP and transmit payment packet.

    Re-serialises packet_json to compact form to strip any formatting
    whitespace that would break newline framing.

    Args:
        packet_json: JSON string from wallet.core.create_payment_packet.
        ip:          Merchant LAN IP from QR.
        port:        TCP port from QR.

    Returns:
        True if merchant replies ACK_SUCCESS, False otherwise.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT_SECONDS)

    try:
        logger.info(f"Connecting to merchant at {ip}:{port} ...")
        sock.connect((ip, port))
        logger.info("Connected.")

        # Re-serialise to compact JSON — removes embedded newlines from
        # wallet.core which uses json.dumps(packet, indent=2).
        compact = json.dumps(json.loads(packet_json), separators=(',', ':'))
        payload = compact.encode('utf-8') + b'\n'
        sock.sendall(payload)
        logger.info(f"Packet sent ({len(compact)} chars). Waiting for ACK...")

        # Read ACK (single-shot; accumulate until newline)
        buffer = b""
        while b'\n' not in buffer:
            chunk = sock.recv(BUFFER_SIZE)
            if not chunk:
                logger.error("Merchant closed connection before sending ACK")
                return False
            buffer += chunk

        ack = buffer.split(b'\n', 1)[0].decode('utf-8', errors='replace')
        logger.info(f"ACK received: {ack}")
        return ack == "ACK_SUCCESS"

    except socket.timeout:
        logger.error("Connection/ACK timed out (5s)")
        return False
    except ConnectionRefusedError:
        logger.error(f"Connection refused at {ip}:{port}")
        return False
    except Exception as e:
        logger.error(f"Transport error: {e}")
        return False
    finally:
        sock.close()
    return False  # unreachable — satisfies Pyre2 missing-return check


if __name__ == "__main__":
    try:
        mid, ip, port = scan_qr()
        print(f"Scanned: {mid} @ {ip}:{port}")
    except Exception as e:
        print(e)
