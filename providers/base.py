from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class StoreProvider(ABC):
    """Abstract base class for e-commerce store backends (Shoppex, SellAuth)."""

    @abstractmethod
    async def get_products(self) -> List[Dict[str, Any]]:
        """Fetch list of active products normalized with id, name, price, currency, stock, description, and url."""
        pass

    @abstractmethod
    async def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single product details by ID."""
        pass

    @abstractmethod
    async def add_stock(self, product_id: str, serials: List[str], variant_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Add serial inventory/keys to a product in real-time.
        Returns a dict: {"success": bool, "added_count": int, "message": str}
        """
        pass

    @abstractmethod
    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch order details by order/invoice ID.
        Returns a normalized dict:
        {
            "id": str,
            "status": str,
            "is_paid": bool,
            "customer_email": str,
            "product_name": str,
            "total": float,
            "currency": str
        }
        """
        pass

    @abstractmethod
    def get_checkout_url(self, product_id: str) -> str:
        """Generate direct public checkout URL for a product."""
        pass
