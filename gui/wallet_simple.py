import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import json
from datetime import datetime

from wallet import core as wallet_core
from wallet import transport as wallet_transport
from shared.paths import WALLET_DB_PATH, WALLET_SALT_PATH


class WalletGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("Offline Payment Wallet")
        self.root.geometry("650x500")

        self.pwd = None

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

    def log(self, text):
        self.output.insert("end", text + "\n")
        self.output.see("end")

    def ask_password(self):
        pwd = simpledialog.askstring("Password", "Enter wallet password", show="*")
        return pwd

    def load_wallet(self):
        pwd = self.ask_password()
        if not pwd:
            return

        try:
            wallet_core.get_or_create_identity(pwd)
            self.pwd = pwd
            messagebox.showinfo("Wallet", "Wallet loaded successfully")
        except Exception:
            messagebox.showerror("Error", "Invalid password")

    def preload_funds(self):
        if not self.pwd:
            messagebox.showwarning("Wallet", "Load wallet first")
            return

        amount = simpledialog.askinteger("Preload Funds", "Enter amount")
        if not amount:
            return

        try:
            count = wallet_core.preload_funds(self.pwd, amount)
            messagebox.showinfo("Success", f"{amount} loaded\nTokens issued: {count}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def check_balance(self):
        if not self.pwd:
            messagebox.showwarning("Wallet", "Load wallet first")
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

        self.log(f"Total Balance : {total}")
        self.log(f"Unspent Tokens: {count}")

        for d in sorted(counts.keys(), reverse=True):
            self.log(f"   {d} x {counts[d]}")

        self.log(f"Spent Tokens  : {spent}")
        self.log(f"Expired Tokens: {expired}")

    def pay_merchant(self):
        if not self.pwd:
            messagebox.showwarning("Wallet", "Load wallet first")
            return

        amount = simpledialog.askinteger("Payment", "Enter amount")
        if not amount:
            return

        try:
            merchant_id, ip, port = wallet_transport.scan_qr()
        except Exception as e:
            messagebox.showerror("QR Error", str(e))
            return

        confirm = messagebox.askyesno(
            "Confirm Payment",
            f"Merchant: {merchant_id}\nAmount: {amount}\nProceed?"
        )

        if not confirm:
            return

        try:
            packet_json = wallet_core.create_payment_packet(self.pwd, merchant_id, amount)
            success = wallet_transport.send_payment(packet_json, ip, port)

            if success:
                data = json.loads(packet_json)
                tx = data.get("transaction_id")

                messagebox.showinfo(
                    "Payment Successful",
                    f"Transaction ID:\n{tx}"
                )
            else:
                messagebox.showerror("Payment Failed", "Merchant rejected payment")

        except Exception as e:
            messagebox.showerror("Payment Failed", str(e))

    def view_tokens(self):
        if not self.pwd:
            messagebox.showwarning("Wallet", "Load wallet first")
            return

        try:
            tokens = wallet_core.get_local_token_details(self.pwd)
        except Exception as e:
            messagebox.showerror("Error", str(e))
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

            messagebox.showinfo(
                "Wallet Identity",
                f"Display Name : {buyer_name}\n"
                f"Internal ID  : {buyer_id}\n"
                f"ID Hash      : {id_hash}"
            )

        except Exception:
            messagebox.showerror("Error", "Invalid password")


def run_gui():
    root = tk.Tk()
    app = WalletGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()