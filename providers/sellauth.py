import aiohttp
import logging
from typing import List, Dict, Any, Optional
from .base import StoreProvider

logger = logging.getLogger(__name__)

class SellAuthProvider(StoreProvider):
    """Integration for SellAuth API (https://api.sellauth.com/v1)."""

    def __init__(self, api_key: str, shop_id: str):
        self.api_key = api_key.strip()
        self.shop_id = shop_id.strip()
        self.base_url = "https://api.sellauth.com/v1"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def get_products(self) -> List[Dict[str, Any]]:
        """Fetch all products for the shop."""
        url = f"{self.base_url}/shops/{self.shop_id}/products"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        logger.error(f"SellAuth get_products failed ({resp.status}): {err_text}")
                        return []
                    data = await resp.json()
                    raw_products = data if isinstance(data, list) else data.get("data", [])
                    if not isinstance(raw_products, list):
                        raw_products = []

                    normalized = []
                    for p in raw_products:
                        pid = str(p.get("id") or "")
                        name = p.get("name") or "Unnamed Product"
                        price = float(p.get("price") or 0.0)
                        currency = p.get("currency") or "USD"
                        stock = p.get("stock", -1)

                        normalized.append({
                            "id": pid,
                            "name": name,
                            "price": price,
                            "currency": currency,
                            "stock": stock,
                            "description": p.get("description") or "",
                            "url": self.get_checkout_url(pid)
                        })
                    return normalized
        except Exception as e:
            logger.error(f"Error fetching SellAuth products: {e}")
            return []

    async def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Fetch single product from SellAuth."""
        url = f"{self.base_url}/shops/{self.shop_id}/products/{product_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return None
                    p = await resp.json()
                    if isinstance(p, dict) and "data" in p:
                        p = p["data"]
                    pid = str(p.get("id") or product_id)
                    return {
                        "id": pid,
                        "name": p.get("name") or "Unnamed Product",
                        "price": float(p.get("price") or 0.0),
                        "currency": p.get("currency") or "USD",
                        "stock": p.get("stock", -1),
                        "description": p.get("description") or "",
                        "url": self.get_checkout_url(pid)
                    }
        except Exception as e:
            logger.error(f"Error fetching SellAuth product {product_id}: {e}")
            return None

    async def add_stock(self, product_id: str, serials: List[str], variant_id: Optional[str] = None) -> Dict[str, Any]:
        """Add serial stock to SellAuth product."""
        if not serials:
            return {"success": False, "added_count": 0, "message": "No serials provided."}

        clean_serials = [s.strip() for s in serials if s.strip()]
        if not clean_serials:
            return {"success": False, "added_count": 0, "message": "Serials list was empty after trimming."}

        # SellAuth accepts serials via stock or serials endpoint
        url = f"{self.base_url}/shops/{self.shop_id}/products/{product_id}/stock"
        payload = {
            "serials": clean_serials
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self._headers(), json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp_json = await resp.json()
                    if resp.status in (200, 201):
                        return {
                            "success": True,
                            "added_count": len(clean_serials),
                            "message": f"Successfully added {len(clean_serials)} item(s) to SellAuth product."
                        }
                    else:
                        error_msg = resp_json.get("message") or str(resp_json)
                        logger.error(f"SellAuth add_stock failed ({resp.status}): {error_msg}")
                        return {
                            "success": False,
                            "added_count": 0,
                            "message": f"SellAuth API Error ({resp.status}): {error_msg}"
                        }
        except Exception as e:
            logger.error(f"Exception during SellAuth add_stock: {e}")
            return {"success": False, "added_count": 0, "message": f"Network exception: {str(e)}"}

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetch order/invoice details from SellAuth."""
        order_id = order_id.strip()
        url = f"{self.base_url}/shops/{self.shop_id}/invoices/{order_id}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    invoice = data.get("data", data)
                    status = str(invoice.get("status") or "").upper()
                    is_paid = status in ["PAID", "COMPLETED"]

                    product_name = ""
                    if invoice.get("product"):
                        product_name = invoice["product"].get("name") or ""

                    return {
                        "id": str(invoice.get("id") or order_id),
                        "status": status,
                        "is_paid": is_paid,
                        "customer_email": invoice.get("email") or "Unknown",
                        "product_name": product_name or "Store Item",
                        "total": float(invoice.get("total") or 0.0),
                        "currency": invoice.get("currency") or "USD"
                    }
        except Exception as e:
            logger.error(f"Error fetching SellAuth invoice {order_id}: {e}")
            return None

    def get_checkout_url(self, product_id: str) -> str:
        """Returns SellAuth purchase link."""
        return f"https://sellauth.com/product/{product_id}"
