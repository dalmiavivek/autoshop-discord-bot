import sqlite3
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

class OrderDatabase:
    """Manages SQLite storage for verified orders, restock history, crypto addresses, and DM invoices."""

    def __init__(self, db_path: str = "orders.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS verified_orders (
                    order_id TEXT PRIMARY KEY,
                    discord_user_id INTEGER NOT NULL,
                    product_id TEXT,
                    product_name TEXT,
                    claimed_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS restock_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    product_name TEXT,
                    quantity_added INTEGER NOT NULL,
                    admin_user_id INTEGER NOT NULL,
                    added_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS crypto_addresses (
                    token TEXT PRIMARY KEY,
                    address TEXT NOT NULL,
                    network TEXT DEFAULT '',
                    payout_forward_address TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS crypto_invoices (
                    invoice_id TEXT PRIMARY KEY,
                    discord_user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    product_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    token TEXT NOT NULL,
                    expected_crypto_amount REAL NOT NULL,
                    fiat_amount REAL NOT NULL,
                    fiat_currency TEXT NOT NULL,
                    deposit_address TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING',
                    txid TEXT DEFAULT '',
                    ticket_channel_id INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    paid_at TEXT
                )
            """)
            conn.commit()

    # --- Verified Orders ---
    def is_order_claimed(self, order_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM verified_orders WHERE order_id = ?", (order_id.strip(),))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def record_verified_order(self, order_id: str, discord_user_id: int, product_id: str = "", product_name: str = "") -> bool:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO verified_orders (order_id, discord_user_id, product_id, product_name, claimed_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (order_id.strip(), discord_user_id, product_id, product_name, now_iso))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def record_restock(self, product_id: str, product_name: str, quantity: int, admin_user_id: int):
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO restock_history (product_id, product_name, quantity_added, admin_user_id, added_at)
                VALUES (?, ?, ?, ?, ?)
            """, (product_id.strip(), product_name, quantity, admin_user_id, now_iso))
            conn.commit()

    # --- Crypto Addresses ---
    def set_crypto_address(self, token: str, address: str, network: str = "", payout_forward_address: str = ""):
        token = token.strip().upper()
        address = address.strip()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO crypto_addresses (token, address, network, payout_forward_address, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    address=excluded.address,
                    network=excluded.network,
                    payout_forward_address=excluded.payout_forward_address,
                    updated_at=excluded.updated_at
            """, (token, address, network, payout_forward_address, now_iso))
            conn.commit()

    def get_crypto_address(self, token: str) -> Optional[Dict[str, Any]]:
        token = token.strip().upper()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM crypto_addresses WHERE token = ?", (token,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_all_crypto_addresses(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM crypto_addresses ORDER BY token ASC")
            return [dict(r) for r in cursor.fetchall()]

    # --- Crypto Invoices ---
    def create_crypto_invoice(
        self,
        invoice_id: str,
        discord_user_id: int,
        guild_id: int,
        product_id: str,
        product_name: str,
        token: str,
        expected_crypto_amount: float,
        fiat_amount: float,
        fiat_currency: str,
        deposit_address: str
    ) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO crypto_invoices (
                        invoice_id, discord_user_id, guild_id, product_id, product_name,
                        token, expected_crypto_amount, fiat_amount, fiat_currency,
                        deposit_address, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """, (
                    invoice_id, discord_user_id, guild_id, product_id, product_name,
                    token.upper(), expected_crypto_amount, fiat_amount, fiat_currency,
                    deposit_address, now_iso
                ))
                conn.commit()
                return True
        except Exception as e:
            return False

    def get_crypto_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM crypto_invoices WHERE invoice_id = ?", (invoice_id.strip(),))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_pending_crypto_invoices(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM crypto_invoices WHERE status = 'PENDING' ORDER BY created_at ASC")
            return [dict(r) for r in cursor.fetchall()]

    def update_invoice_status(self, invoice_id: str, status: str, txid: str = "", ticket_channel_id: int = 0):
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE crypto_invoices
                SET status = ?, txid = CASE WHEN ? != '' THEN ? ELSE txid END,
                    ticket_channel_id = CASE WHEN ? != 0 THEN ? ELSE ticket_channel_id END,
                    paid_at = CASE WHEN ? = 'PAID' THEN ? ELSE paid_at END
                WHERE invoice_id = ?
            """, (status, txid, txid, ticket_channel_id, ticket_channel_id, status, now_iso, invoice_id))
            conn.commit()

    def is_txid_used(self, txid: str) -> bool:
        if not txid or not txid.strip():
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT invoice_id FROM crypto_invoices WHERE txid = ? AND status = 'PAID'", (txid.strip(),))
            return cursor.fetchone() is not None

