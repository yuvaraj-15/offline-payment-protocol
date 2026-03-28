import tkinter as tk
from tkinter import ttk

from gui.wallet_gui import WalletGUI
from gui.merchant_gui import MerchantGUI


class MainGUI:

    def __init__(self):

        self.root = tk.Tk()
        self.root.title("Offline Payment Protocol")
        self.root.geometry("420x240")

        ttk.Label(
            self.root,
            text="Offline Payment System",
            font=("Arial", 18, "bold")
        ).pack(pady=20)

        frame = ttk.Frame(self.root)
        frame.pack()

        ttk.Button(
            frame,
            text="Wallet",
            width=20,
            command=self.open_wallet
        ).grid(row=0, column=0, padx=10)

        ttk.Button(
            frame,
            text="Merchant",
            width=20,
            command=self.open_merchant
        ).grid(row=0, column=1, padx=10)

    def open_wallet(self):
        wallet_window = tk.Toplevel(self.root)
        WalletGUI(wallet_window)

    def open_merchant(self):
        MerchantGUI(self.root)


def main():
    app = MainGUI()
    app.root.mainloop()