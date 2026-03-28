import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import subprocess
import sys
import socket
import qrcode
from PIL import ImageTk

from merchant import database as merch_db
from merchant import settlement as merch_settlement


class MerchantGUI:

    def __init__(self, parent):

        self.win = tk.Toplevel(parent)
        self.win.title("Merchant")
        self.win.geometry("600x480")

        self.server = None

        self.merchant_id = tk.StringVar(value="Not initialized")

        ttk.Label(
            self.win,
            text="Merchant Terminal",
            font=("Arial", 16, "bold")
        ).pack(pady=10)

        frame = ttk.LabelFrame(self.win, text="Identity", padding=10)
        frame.pack(fill="x", padx=10)

        ttk.Label(frame, text="Merchant ID").grid(row=0, column=0)
        ttk.Label(frame, textvariable=self.merchant_id).grid(row=0, column=1)

        ttk.Button(
            frame,
            text="Load Identity",
            command=self.load_identity
        ).grid(row=0, column=2)

        self.qr_label = ttk.Label(self.win)
        self.qr_label.pack(pady=20)

        ttk.Button(
            self.win,
            text="Start Server",
            command=self.start_server
        ).pack(pady=10)

        ttk.Button(
            self.win,
            text="Settle with Bank",
            command=self.settle
        ).pack(pady=10)

    def load_identity(self):

        merch_db.init_db()

        mid = merch_db.load_config("merchant_id")

        if not mid:

            name = simpledialog.askstring("Merchant Name", "Enter merchant name")

            import uuid

            mid = "Merchant-" + uuid.uuid4().hex

            merch_db.save_config("merchant_id", mid)
            merch_db.save_config("merchant_display_name", name)

        self.merchant_id.set(mid)

    def get_ip(self):

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        s.connect(("8.8.8.8", 80))

        ip = s.getsockname()[0]

        s.close()

        return ip

    def start_server(self):

        mid = self.merchant_id.get()

        ip = self.get_ip()

        port = 5050

        cmd = [sys.executable, "-m", "merchant.transport", mid, "--headless"]

        self.server = subprocess.Popen(cmd)

        payload = {
            "merchant_id": mid,
            "ip": ip,
            "port": port
        }

        qr = qrcode.make(payload)

        img = ImageTk.PhotoImage(qr)

        self.qr_label.config(image=img)
        self.qr_label.image = img

    def settle(self):

        try:

            count = merch_settlement.settle_pending_transactions()

            messagebox.showinfo("Settlement", f"{count} transactions settled")

        except Exception as e:

            messagebox.showerror("Error", str(e))