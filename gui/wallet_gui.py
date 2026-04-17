import tkinter as tk
from tkinter import ttk, simpledialog
import sqlite3
import json
from datetime import datetime

from wallet import core as wallet_core
from wallet import transport as wallet_transport
from shared.paths import WALLET_DB_PATH, WALLET_SALT_PATH
import os

def wallet_exists():
    return WALLET_SALT_PATH.exists() and WALLET_DB_PATH.exists()


class WalletGUI:
    def create_wallet_dialog(self):

        win = tk.Toplevel(self.root)
        win.title("Create Wallet")
        win.geometry("320x320")
        win.grab_set()

        frame = ttk.Frame(win, padding=15)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Create New Wallet", font=("Arial", 12, "bold")).pack(pady=5)

        ttk.Label(frame, text="Display Name").pack(anchor="w")
        name_entry = ttk.Entry(frame)
        name_entry.pack(fill="x", pady=3)

        ttk.Label(frame, text="Password").pack(anchor="w")
        pwd_entry = ttk.Entry(frame, show="*")
        pwd_entry.pack(fill="x", pady=3)

        ttk.Label(frame, text="Confirm Password").pack(anchor="w")
        pwd2_entry = ttk.Entry(frame, show="*")
        pwd2_entry.pack(fill="x", pady=3)

        def create_wallet():

            name = name_entry.get().strip()
            pwd = pwd_entry.get()
            pwd2 = pwd2_entry.get()

            if not name:
                self.notify("Display name required")
                return

            if pwd != pwd2:
                self.notify("Passwords do not match")
                return

            try:
                wallet_core.get_or_create_identity(pwd, display_name=name)
                self.pwd = pwd
                self.notify(f"Wallet created for {name}")
                win.destroy()
            except Exception as e:
                self.notify(f"Wallet creation failed: {e}")

        ttk.Button(frame, text="Create Wallet", command=create_wallet).pack(pady=10)

        self.root.wait_window(win)

    def notify(self, msg):
        if hasattr(self, "output") and self.output:
            self.output.insert("end", msg + "\n")
            self.output.see("end")
        else:
            print(msg)   

    def __init__(self, root):

        self.root = root
        self.root.title("Offline Payment Wallet")
        self.root.geometry("650x600")

        if not wallet_exists():
            self.create_wallet_dialog()
        else:
            self.notify("Wallet detected. Please load wallet.")

        title = ttk.Label(root, text="Offline Payment Wallet", font=("Arial", 18, "bold"))
        title.pack(pady=10)

        btn_frame = ttk.Frame(root)
        btn_frame.pack(pady=10)

        ttk.Button(btn_frame, text="Load Wallet", width=20, command=self.load_wallet).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(btn_frame, text="Preload Funds", width=20, command=self.preload_funds).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(btn_frame, text="Check Balance", width=20, command=self.check_balance).grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(btn_frame, text="Pay Merchant", width=20, command=self.pay_merchant).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(btn_frame, text="View Tokens", width=20, command=self.view_tokens).grid(row=2, column=0, padx=5, pady=5)
        ttk.Button(btn_frame, text="Wallet Identity", width=20, command=self.view_identity).grid(row=2, column=1, padx=5, pady=5)

        self.output = tk.Text(root, height=15)
        self.output.pack(fill="both", expand=True, padx=10, pady=10)

    def ask_password(self):
        return simpledialog.askstring("Password", "Enter wallet password", show="*")

    def create_wallet(self, pwd):

        name = simpledialog.askstring("Create Wallet", "Enter Display Name")

        if not name:
            self.notify("Wallet creation cancelled")
            return False

        try:
            wallet_core.get_or_create_identity(pwd, display_name=name)
            self.notify(f"Wallet created for {name}")
            return True
        except Exception as e:
            self.notify(f"Wallet creation failed: {e}")
            return False

    def load_wallet(self):

        pwd = self.ask_password()
        if not pwd:
            return

        try:
            wallet_core.get_or_create_identity(pwd)
            self.pwd = pwd
            self.notify("Wallet loaded successfully")

        except Exception:

            self.notify("Wallet not found or invalid password")

            create = simpledialog.askstring(
                "Create Wallet",
                "Wallet does not exist.\nEnter display name to create one:"
            )

            if create:
                try:
                    wallet_core.get_or_create_identity(pwd, display_name=create)
                    self.pwd = pwd
                    self.notify(f"Wallet created for {create}")
                except Exception as e:
                    self.notify(f"Wallet creation failed: {e}")

    def preload_funds(self):

        if not self.pwd:
            self.notify("Load wallet first")
            return

        amount = simpledialog.askinteger("Preload Funds", "Enter amount")
        if not amount:
            return

        try:
            count = wallet_core.preload_funds(self.pwd, amount)
            self.notify(f"SUCCESS: {amount} loaded | Tokens issued: {count}")
        except Exception as e:
            self.notify(f"Error: {e}")

    def check_balance(self):

        if not self.pwd:
            self.notify("Load wallet first")
            return

        try:
            from wallet import database as wallet_db
            wallet_db.expire_stale_tokens()
        except Exception:
            pass

        with sqlite3.connect(WALLET_DB_PATH) as conn:

            rows = conn.execute(
                "SELECT denomination FROM tokens WHERE status='UNSPENT'"
            ).fetchall()

            total = sum(r[0] for r in rows)
            count = len(rows)

            counts = {}

            for r in rows:
                d = r[0]
                counts[d] = counts.get(d, 0) + 1

            spent = conn.execute(
                "SELECT COUNT(*) FROM tokens WHERE status='SPENT'"
            ).fetchone()[0]

            expired = conn.execute(
                "SELECT COUNT(*) FROM tokens WHERE status='EXPIRED'"
            ).fetchone()[0]

        self.output.delete("1.0", "end")

        self.notify(f"Total Balance : {total}")
        self.notify(f"Unspent Tokens: {count}")

        for d in sorted(counts.keys(), reverse=True):
            self.notify(f"   {d} x {counts[d]}")

        self.notify(f"Spent Tokens  : {spent}")
        self.notify(f"Expired Tokens: {expired}")

    def confirm_dialog(self, title, message):

        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("320x250")
        win.grab_set()

        result = {"value": False}

        frame = ttk.Frame(win, padding=15)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=message, justify="center", wraplength=280).pack(pady=10)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)

        def yes():
            result["value"] = True
            win.destroy()

        def no():
            win.destroy()

        ttk.Button(btn_frame, text="Yes", command=yes).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="No", command=no).pack(side="left", padx=10)

        self.root.wait_window(win)

        return result["value"]

    def pay_merchant(self):

        if not self.pwd:
            self.notify("Load wallet first")
            return

        amount = simpledialog.askinteger("Payment", "Enter amount")
        if not amount:
            return

        try:
            merchant_id, ip, port = wallet_transport.scan_qr()
        except Exception as e:
            self.notify(f"QR Error: {e}")
            return

        confirm = self.confirm_dialog(
            "Confirm Payment",
            f"Merchant: {merchant_id}\nAmount: {amount}\nProceed?"
        )

        if not confirm:
            self.notify("Payment cancelled")
            return

        try:
            packet_json = wallet_core.create_payment_packet(self.pwd, merchant_id, amount)
            success = wallet_transport.send_payment(packet_json, ip, port)

            if success:
                data = json.loads(packet_json)
                tx = data.get("transaction_id")
                self.notify(f"Payment Successful | Transaction ID: {tx}")
            else:
                self.notify("Payment rejected by merchant")

        except Exception as e:
            self.notify(f"Payment Failed: {e}")

    def view_tokens(self):

        if not self.pwd:
            self.notify("Load wallet first")
            return

        try:
            tokens = wallet_core.get_local_token_details(self.pwd)
        except Exception as e:
            self.notify(f"Error: {e}")
            return

        win = tk.Toplevel(self.root)
        win.title("Local Tokens")

        cols = ("Token ID", "Amount", "Status", "Issued", "Expiry")

        tree = ttk.Treeview(win, columns=cols, show="headings")
        tree.pack(fill="both", expand=True)

        for c in cols:
            tree.heading(c, text=c)

        for t in tokens:
            tree.insert(
                "",
                "end",
                values=(
                    t["token_id"][:8],
                    t["denomination"],
                    t["status"],
                    datetime.fromtimestamp(t["issue_timestamp"]),
                    datetime.fromtimestamp(t["expiry_timestamp"]),
                ),
            )

    def view_identity(self):

        pwd = self.ask_password()
        if not pwd:
            return

        try:

            from wallet import crypto as wallet_crypto
            from wallet import database as wallet_db
            import hashlib

            with open(WALLET_SALT_PATH, "rb") as f:
                salt = f.read()

            key, _ = wallet_crypto.derive_key(pwd, salt)

            buyer_id = wallet_db.load_config("buyer_id", key)
            buyer_name = wallet_db.load_config("buyer_display_name", key)

            id_hash = hashlib.sha256(buyer_id.encode()).hexdigest()

            self.notify(f"Display Name : {buyer_name}")
            self.notify(f"Internal ID  : {buyer_id}")
            self.notify(f"ID Hash      : {id_hash}")

        except Exception:
            self.notify("Invalid password")


def run_gui():
    root = tk.Tk()
    WalletGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()