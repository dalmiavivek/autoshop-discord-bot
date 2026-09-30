import sqlite3
import os
from typing import Optional, Dict, Any
from datetime import datetime, timezone

class OrderDatabase:
    """Manages SQLite storage for verified orders to prevent duplicate claims."""

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
            conn.commit()

    def is_order_claimed(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Check if an order has already been verified and claimed."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM verified_orders WHERE order_id = ?", (order_id.strip(),))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def record_verified_order(self, order_id: str, discord_user_id: int, product_id: str = "", product_name: str = "") -> bool:
        """Record an order as verified. Returns True if successful, False if already exists."""
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
        """Record a restock event in history."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO restock_history (product_id, product_name, quantity_added, admin_user_id, added_at)
                VALUES (?, ?, ?, ?, ?)
            """, (product_id.strip(), product_name, quantity, admin_user_id, now_iso))
            conn.commit()
