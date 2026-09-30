import os
import unittest
import asyncio
from database import OrderDatabase
from providers.shoppex import ShoppexProvider
from providers.sellauth import SellAuthProvider
from providers import get_store_provider

class TestAutoShopBot(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Use in-memory or temp SQLite DB for testing
        self.test_db_path = "test_orders.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.db = OrderDatabase(self.test_db_path)

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_database_order_redemption(self):
        """Test that orders can be recorded and duplicates are prevented."""
        order_id = "ord_test_998877"
        user_id = 123456789

        # Initially not claimed
        self.assertIsNone(self.db.is_order_claimed(order_id))

        # Record claim
        success = self.db.record_verified_order(order_id, user_id, "prod_1", "Test Product")
        self.assertTrue(success)

        # Should now be claimed
        record = self.db.is_order_claimed(order_id)
        self.assertIsNotNone(record)
        self.assertEqual(record["discord_user_id"], user_id)
        self.assertEqual(record["product_name"], "Test Product")

        # Second claim attempt should fail
        duplicate = self.db.record_verified_order(order_id, 987654321, "prod_1", "Test Product")
        self.assertFalse(duplicate)

    def test_database_restock_history(self):
        """Test recording restocks."""
        self.db.record_restock("prod_1", "VIP Access", 10, 123456789)
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM restock_history WHERE product_id = ?", ("prod_1",))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["quantity_added"], 10)

    def test_shoppex_provider_urls_and_headers(self):
        """Test Shoppex provider headers and URL construction."""
        provider = ShoppexProvider(api_key="test_shoppex_key", store_domain="mystore.shoppex.io")
        headers = provider._headers()
        self.assertEqual(headers["Authorization"], "Bearer test_shoppex_key")
        self.assertEqual(headers["Content-Type"], "application/json")

        checkout_url = provider.get_checkout_url("prod_123")
        self.assertEqual(checkout_url, "https://mystore.shoppex.io/product/prod_123")

    def test_sellauth_provider_urls_and_headers(self):
        """Test SellAuth provider headers and URL construction."""
        provider = SellAuthProvider(api_key="test_sellauth_key", shop_id="shop_555")
        headers = provider._headers()
        self.assertEqual(headers["Authorization"], "Bearer test_sellauth_key")

        checkout_url = provider.get_checkout_url("prod_456")
        self.assertEqual(checkout_url, "https://sellauth.com/product/prod_456")

    def test_provider_factory(self):
        """Test factory picks Shoppex and SellAuth based on env."""
        os.environ["STORE_PLATFORM"] = "shoppex"
        os.environ["SHOPPEX_API_KEY"] = "key1"
        os.environ["SHOPPEX_STORE_DOMAIN"] = "test.shoppex.io"
        p1 = get_store_provider()
        self.assertIsInstance(p1, ShoppexProvider)

        os.environ["STORE_PLATFORM"] = "sellauth"
        os.environ["SELLAUTH_API_KEY"] = "key2"
        os.environ["SELLAUTH_SHOP_ID"] = "shop_1"
        p2 = get_store_provider()
        self.assertIsInstance(p2, SellAuthProvider)

    async def test_shoppex_add_stock_empty(self):
        """Test add_stock with empty inputs."""
        provider = ShoppexProvider("dummy_key", "test.shoppex.io")
        res1 = await provider.add_stock("p1", [])
        self.assertFalse(res1["success"])
        res2 = await provider.add_stock("p1", ["   ", "\n"])
        self.assertFalse(res2["success"])

    async def test_sellauth_add_stock_empty(self):
        """Test SellAuth add_stock with empty inputs."""
        provider = SellAuthProvider("dummy_key", "shop_1")
        res1 = await provider.add_stock("p1", [])
        self.assertFalse(res1["success"])
        res2 = await provider.add_stock("p1", ["   ", "\n"])
        self.assertFalse(res2["success"])

if __name__ == "__main__":
    unittest.main()
