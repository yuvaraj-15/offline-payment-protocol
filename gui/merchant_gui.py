import tkinter as tk
from tkinter import ttk
import threading
import sqlite3
import datetime

from merchant import transport as merch_transport
from merchant import database as merch_db
from merchant import settlement as merch_settlement


class MerchantGUI:

    def __init__(self, parent):

        self.root = tk.Toplevel(parent)
        self.root.title("Merchant Terminal")
        self.root.geometry("720x520")

        self.mid = None
        self.server_running = False
        self.server_socket = None

        ttk.Label(
            self.root,
            text="Offline Payment Merchant",
            font=("Arial", 16, "bold")
        ).pack(pady=10)

        id_frame = ttk.LabelFrame(self.root, text="Merchant Identity", padding=10)
        id_frame.pack(fill="x", padx=10)

        self.name_var = tk.StringVar(value="Unknown")
        self.id_var = tk.StringVar(value="Not Initialized")

        ttk.Label(id_frame, text="Name").grid(row=0, column=0, sticky="w")
        ttk.Label(id_frame, textvariable=self.name_var).grid(row=0, column=1, sticky="w")

        ttk.Label(id_frame, text="Merchant ID").grid(row=1, column=0, sticky="w")
        ttk.Label(id_frame, textvariable=self.id_var).grid(row=1, column=1, sticky="w")

        ttk.Button(
            id_frame,
            text="Initialize Merchant",
            command=self.init_identity
        ).grid(row=0, column=2, rowspan=2, padx=10)

        actions = ttk.LabelFrame(self.root, text="Actions", padding=10)
        actions.pack(fill="x", padx=10, pady=10)

        ttk.Button(actions, text="Start Payment Server", command=self.start_server).grid(row=0, column=0, padx=5)
        ttk.Button(actions, text="Stop Server", command=self.stop_server).grid(row=0, column=1, padx=5)
        ttk.Button(actions, text="View Pending", command=self.view_pending).grid(row=0, column=2, padx=5)
        ttk.Button(actions, text="View Settled", command=self.view_settled).grid(row=0, column=3, padx=5)
        ttk.Button(actions, text="Settle with Bank", command=self.settle).grid(row=0, column=4, padx=5)

        qr_frame = ttk.LabelFrame(self.root, text="Merchant QR Code", padding=10)
        qr_frame.pack(padx=10, pady=10)

        self.banner = tk.Label(
            self.root,
            text="",
            bg="#2ecc71",
            fg="white",
            font=("Arial", 12, "bold"),
            pady=6
        )

        self.banner.pack(fill="x")
        self.banner.pack_forget()  

        self.qr_label = ttk.Label(qr_frame)
        self.qr_label.pack()

        log_frame = ttk.LabelFrame(self.root, text="Transaction Log", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        cols = ("tx", "buyer", "amount", "timestamp", "status")

        self.tree = ttk.Treeview(log_frame, columns=cols, show="headings")
        self.tree.pack(fill="both", expand=True)

        for c in cols:
            self.tree.heading(c, text=c)

        self.init_identity()

    def notify(self, msg):
        print(msg)

    def notify_popup(self, msg, duration=10000):

        self.banner.config(text=msg)
        self.banner.pack(fill="x")

        self.root.after(duration, self.banner.pack_forget)

    def get_db(self):

        conn = sqlite3.connect(merch_db.DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def init_identity(self):

        import uuid

        mid = merch_db.load_config("merchant_id")

        if not mid:

            name = tk.simpledialog.askstring("Merchant", "Enter Merchant Display Name")

            if not name:
                return

            mid = f"Merchant-{uuid.uuid4().hex}"

            merch_db.save_config("merchant_id", mid)
            merch_db.save_config("merchant_display_name", name)

        name = merch_db.load_config("merchant_display_name") or "Unknown"

        self.mid = mid

        self.name_var.set(name)
        self.id_var.set(mid)

    def payment_received(self, packet_json):

        import json

        try:
            data = json.loads(packet_json)

            tx = data.get("transaction_id")
            amount = data.get("requested_amount")
            buyer = data.get("buyer_id_hash", "")[:8]

            msg = f"Payment Received | ₹{amount} | Buyer {buyer}"

            self.notify(msg)            
            self.notify_popup(msg)      

        except Exception:
            self.notify_popup("Payment received")

    def start_server(self):

        if self.server_running:
            self.notify("Server already running")
            return

        from PIL import Image, ImageTk

        qr_img, self.server_socket = merch_transport.start_server_gui(
            self.mid,
            notify_callback=self.payment_received
        )

        img = Image.fromarray(qr_img).resize((250, 250))
        tk_img = ImageTk.PhotoImage(img)

        self.qr_label.configure(image=tk_img)
        self.qr_label.image = tk_img

        self.server_running = True

        self.notify("Payment server started")

    def stop_server(self):

        if not self.server_running:
            self.notify("Server not running")
            return

        try:
            self.server_socket.close()
        except:
            pass

        self.qr_label.configure(image="")
        self.qr_label.image = None

        self.server_running = False

        self.notify("Payment server stopped")

    def view_pending(self):

        for row in self.tree.get_children():
            self.tree.delete(row)

        with self.get_db() as conn:
            rows = conn.execute(
                "SELECT transaction_id, total_amount, timestamp "
                "FROM transactions WHERE status='PENDING'"
            ).fetchall()

        for r in rows:

            ts = datetime.datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")

            self.tree.insert("", "end", values=(r["transaction_id"][:8], "-", r["total_amount"], ts, "PENDING"))

    def view_settled(self):

        for row in self.tree.get_children():
            self.tree.delete(row)

        with self.get_db() as conn:
            rows = conn.execute(
                "SELECT transaction_id, total_amount, timestamp "
                "FROM transactions WHERE status='SETTLED'"
            ).fetchall()

        for r in rows:

            ts = datetime.datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")

            self.tree.insert("", "end", values=(r["transaction_id"][:8], "-", r["total_amount"], ts, "SETTLED"))

    def settle(self):

        try:

            count = merch_settlement.settle_pending_transactions()

            self.notify(f"Settlement complete: {count} transactions")

        except Exception as e:

            self.notify(f"Settlement error: {e}")