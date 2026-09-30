import os
import logging
from typing import Optional
from .base import StoreProvider
from .shoppex import ShoppexProvider
from .sellauth import SellAuthProvider

logger = logging.getLogger(__name__)

def get_store_provider() -> Optional[StoreProvider]:
    """Factory to instantiate the configured store provider (Shoppex or SellAuth)."""
    platform = os.getenv("STORE_PLATFORM", "shoppex").strip().lower()

    if platform == "shoppex":
        api_key = os.getenv("SHOPPEX_API_KEY", "").strip()
        domain = os.getenv("SHOPPEX_STORE_DOMAIN", "").strip()
        if not api_key:
            logger.warning("SHOPPEX_API_KEY is not set in environment.")
        return ShoppexProvider(api_key=api_key, store_domain=domain)

    elif platform == "sellauth":
        api_key = os.getenv("SELLAUTH_API_KEY", "").strip()
        shop_id = os.getenv("SELLAUTH_SHOP_ID", "").strip()
        if not api_key or not shop_id:
            logger.warning("SELLAUTH_API_KEY or SELLAUTH_SHOP_ID is not set in environment.")
        return SellAuthProvider(api_key=api_key, shop_id=shop_id)

    else:
        logger.error(f"Unknown STORE_PLATFORM: {platform}. Expected 'shoppex' or 'sellauth'.")
        return None
