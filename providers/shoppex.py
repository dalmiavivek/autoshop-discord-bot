import aiohttp
import logging
from typing import List, Dict, Any, Optional
from .base import StoreProvider

logger = logging.getLogger(__name__)

class ShoppexProvider(StoreProvider):
    """Integration for Shoppex Developer API (https://api.shoppex.io)."""

    def __init__(self, api_key: str, store_domain: str = ""):
        self.api_key = api_key.strip()
        self.store_domain = store_domain.strip().replace("https://", "").replace("http://", "").rstrip("/")
        self.base_url = "https://api.shoppex.io"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def get_products(self) -> List[Dict[str, Any]]:
        """Fetch all products from Shoppex."""
        url = f"{self.base_url}/dev/v1/products"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        logger.error(f"Shoppex get_products failed ({resp.status}): {err_text}")
                        return []
                    data = await resp.json()
                    raw_products = data.get("data", data) if isinstance(data, dict) else data
                    if not isinstance(raw_products, list):
                        raw_products = []

                    normalized = []
                    for p in raw_products:
                        pid = str(p.get("id") or p.get("uniqid") or "")
                        slug = str(p.get("slug") or pid)
                        title = p.get("title") or p.get("name") or "Unnamed Product"
                        price = float(p.get("price") or 0.0)
                        currency = p.get("currency") or "USD"
                        stock = p.get("stock")
                        if stock is None:
                            stock = p.get("available_stock", -1)

                        normalized.append({
                            "id": pid,
                            "slug": slug,
                            "name": title,
                            "price": price,
                            "currency": currency,
                            "stock": stock,
                            "description": p.get("description") or "",
                            "url": self.get_checkout_url(slug)
                        })
                    return normalized
        except Exception as e:
            logger.error(f"Error fetching products from Shoppex: {e}")
            return []

    async def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Fetch details for a single product."""
        url = f"{self.base_url}/dev/v1/products/{product_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    p = data.get("data", data)
                    pid = str(p.get("id") or p.get("uniqid") or product_id)
                    slug = str(p.get("slug") or pid)
                    return {
                        "id": pid,
                        "slug": slug,
                        "name": p.get("title") or p.get("name") or "Unnamed Product",
                        "price": float(p.get("price") or 0.0),
                        "currency": p.get("currency") or "USD",
                        "stock": p.get("stock", p.get("available_stock", -1)),
                        "description": p.get("description") or "",
                        "url": self.get_checkout_url(slug)
                    }
        except Exception as e:
            logger.error(f"Error getting Shoppex product {product_id}: {e}")
            return None

    async def add_stock(self, product_id: str, serials: List[str], variant_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Add serials/keys to a product or variant.
        Uses POST /dev/v1/products/{id}/serials or /dev/v1/products/{id}/variants/{variant_id}/serials.
        """
        if not serials:
            return {"success": False, "added_count": 0, "message": "No serials provided."}

        clean_serials = [s.strip() for s in serials if s.strip()]
        if not clean_serials:
            return {"success": False, "added_count": 0, "message": "Serials list was empty after trimming."}

        newline_separated = "\n".join(clean_serials)

        if variant_id:
            url = f"{self.base_url}/dev/v1/products/{product_id}/variants/{variant_id}/serials"
        else:
            url = f"{self.base_url}/dev/v1/products/{product_id}/serials"

        payload = {
            "serials": newline_separated,
            "remove_duplicates": True
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self._headers(), json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp_json = await resp.json()
                    if resp.status in (200, 201):
                        data = resp_json.get("data", resp_json)
                        added = data.get("added_count", len(clean_serials)) if isinstance(data, dict) else len(clean_serials)
                        return {
                            "success": True,
                            "added_count": added,
                            "message": f"Successfully added {added} item(s) to Shoppex product."
                        }
                    else:
                        error_msg = resp_json.get("message") or resp_json.get("error") or str(resp_json)
                        logger.error(f"Shoppex add_stock failed ({resp.status}): {error_msg}")
                        return {
                            "success": False,
                            "added_count": 0,
                            "message": f"Shoppex API Error ({resp.status}): {error_msg}"
                        }
        except Exception as e:
            logger.error(f"Exception during Shoppex add_stock: {e}")
            return {"success": False, "added_count": 0, "message": f"Network exception: {str(e)}"}

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetch order details from Shoppex (/dev/v1/orders/{id} or /dev/v1/invoices/{id})."""
        order_id = order_id.strip()
        url = f"{self.base_url}/dev/v1/orders/{order_id}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    # If /orders endpoint doesn't find it, fallback to /invoices
                    if resp.status == 404:
                        fallback_url = f"{self.base_url}/dev/v1/invoices/{order_id}"
                        async with session.get(fallback_url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=15)) as f_resp:
                            if f_resp.status != 200:
                                return None
                            data = await f_resp.json()
                    elif resp.status != 200:
                        return None
                    else:
                        data = await resp.json()

                    order = data.get("data", data)
                    status = str(order.get("status") or "").upper()
                    is_paid = status in ["PAID", "COMPLETED", "FULFILLED", "SUCCESS"]

                    product_name = ""
                    items = order.get("items") or order.get("line_items") or []
                    if items and isinstance(items, list):
                        product_name = items[0].get("title") or items[0].get("name") or ""
                    elif order.get("product"):
                        prod = order["product"]
                        product_name = prod.get("title") or prod.get("name") or ""

                    return {
                        "id": str(order.get("id") or order.get("uniqid") or order_id),
                        "status": status,
                        "is_paid": is_paid,
                        "customer_email": order.get("customer_email") or order.get("email") or "Unknown",
                        "product_name": product_name or "Store Item",
                        "total": float(order.get("total") or order.get("amount") or 0.0),
                        "currency": order.get("currency") or "USD"
                    }
        except Exception as e:
            logger.error(f"Error checking Shoppex order {order_id}: {e}")
            return None

    def get_checkout_url(self, product_id: str) -> str:
        """Returns direct store purchase link."""
        if self.store_domain:
            return f"https://{self.store_domain}/product/{product_id}"
        return f"https://shoppex.io/product/{product_id}"
