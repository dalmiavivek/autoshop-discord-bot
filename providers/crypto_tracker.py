import aiohttp
import logging
import time
import urllib.parse
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Cache for crypto prices: { "LTC_USD": (price, timestamp) }
PRICE_CACHE: Dict[str, tuple[float, float]] = {}

async def get_crypto_price(token: str, fiat: str = "USD") -> float:
    """Fetch live crypto price in USD/EUR from Binance or CoinGecko with 60-second caching."""
    token = token.upper().strip()
    fiat = fiat.upper().strip()

    if token == "USDT":
        return 1.0

    cache_key = f"{token}_{fiat}"
    now = time.time()
    if cache_key in PRICE_CACHE:
        val, ts = PRICE_CACHE[cache_key]
        if now - ts < 60:
            return val

    # Try Binance API first
    binance_symbol = f"{token}USDT"
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    usd_price = float(data.get("price", 0.0))
                    if usd_price > 0:
                        # Convert to EUR if requested
                        final_price = usd_price
                        if fiat == "EUR":
                            eur_url = "https://api.binance.com/api/v3/ticker/price?symbol=EURUSDT"
                            async with session.get(eur_url, timeout=aiohttp.ClientTimeout(total=5)) as eur_resp:
                                if eur_resp.status == 200:
                                    eur_data = await eur_resp.json()
                                    eur_rate = float(eur_data.get("price", 1.08))
                                    final_price = usd_price / eur_rate if eur_rate > 0 else usd_price

                        PRICE_CACHE[cache_key] = (final_price, now)
                        return final_price
    except Exception as e:
        logger.warning(f"Binance price fetch failed for {token}: {e}")

    # Fallback default hardcoded approximate prices if APIs are unreachable
    fallback_prices = {
        "LTC": 67.0,
        "BTC": 65000.0,
        "SOL": 140.0,
        "ETH": 2600.0,
        "USDT": 1.0
    }
    return fallback_prices.get(token, 1.0)


def calculate_invoice_crypto_amount(fiat_amount: float, crypto_price: float, invoice_seed: int, token: str) -> float:
    """
    Calculates exact crypto amount needed for the fiat total, adding a small micro-offset
    (e.g., +0.0001 LTC) so each pending order has a unique exact amount to distinguish buyers.
    """
    if crypto_price <= 0:
        crypto_price = 1.0

    raw_crypto = fiat_amount / crypto_price

    if token == "LTC":
        # Add micro offset: 0.0001 to 0.0009
        offset = ((invoice_seed % 80) + 1) * 0.00001
        return round(raw_crypto + offset, 5)
    elif token == "BTC":
        offset = ((invoice_seed % 80) + 1) * 0.0000001
        return round(raw_crypto + offset, 7)
    elif token == "USDT":
        # For USDT, add cents: e.g. 5.03 USDT
        offset = ((invoice_seed % 50) + 1) * 0.01
        return round(raw_crypto + offset, 2)
    elif token == "SOL":
        offset = ((invoice_seed % 80) + 1) * 0.0001
        return round(raw_crypto + offset, 4)
    else:
        return round(raw_crypto, 4)


def get_qr_code_url(token: str, address: str, amount: float) -> str:
    """Generates QR code image URL for mobile crypto wallet scanning."""
    token = token.upper()
    if token == "LTC":
        uri = f"litecoin:{address}?amount={amount}"
    elif token == "BTC":
        uri = f"bitcoin:{address}?amount={amount}"
    elif token == "SOL":
        uri = f"solana:{address}?amount={amount}"
    else:
        uri = address

    encoded = urllib.parse.quote(uri)
    return f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={encoded}"


async def check_incoming_blockchain_tx(
    token: str,
    address: str,
    expected_amount: float
) -> Optional[Dict[str, Any]]:
    """
    Queries public blockchain explorers in real-time to check if a matching
    transaction has been received by the admin address.
    """
    token = token.upper().strip()
    address = address.strip()

    # 1. Litecoin Check via litecoinspace.org (Open source Mempool API)
    if token == "LTC":
        url = f"https://litecoinspace.org/api/address/{address}/txs"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        return None
                    txs = await resp.json()
                    if not isinstance(txs, list):
                        return None

                    for tx in txs:
                        txid = tx.get("txid", "")
                        status = tx.get("status", {})
                        confirmed = status.get("confirmed", False)

                        # Check each output in transaction
                        for out in tx.get("vout", []):
                            out_addr = out.get("scriptpubkey_address", "")
                            val_sats = out.get("value", 0)
                            ltc_val = round(val_sats / 100_000_000.0, 5)

                            # Compare with expected amount (allowing tolerance for dust fees)
                            if out_addr.lower() == address.lower() and abs(ltc_val - expected_amount) <= 0.00005:
                                return {
                                    "found": True,
                                    "confirmed": confirmed,
                                    "txid": txid,
                                    "amount": ltc_val,
                                    "token": "LTC",
                                    "explorer_url": f"https://litecoinspace.org/tx/{txid}"
                                }
        except Exception as e:
            logger.error(f"Error checking LTC blockchain for {address}: {e}")
            return None

    # 2. Bitcoin Check via mempool.space
    elif token == "BTC":
        url = f"https://mempool.space/api/address/{address}/txs"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        return None
                    txs = await resp.json()
                    if not isinstance(txs, list):
                        return None

                    for tx in txs:
                        txid = tx.get("txid", "")
                        status = tx.get("status", {})
                        confirmed = status.get("confirmed", False)

                        for out in tx.get("vout", []):
                            out_addr = out.get("scriptpubkey_address", "")
                            val_sats = out.get("value", 0)
                            btc_val = round(val_sats / 100_000_000.0, 7)

                            if out_addr.lower() == address.lower() and abs(btc_val - expected_amount) <= 0.000001:
                                return {
                                    "found": True,
                                    "confirmed": confirmed,
                                    "txid": txid,
                                    "amount": btc_val,
                                    "token": "BTC",
                                    "explorer_url": f"https://mempool.space/tx/{txid}"
                                }
        except Exception as e:
            logger.error(f"Error checking BTC blockchain for {address}: {e}")
            return None

    # 3. USDT (TRC-20) Check via Tronscan API
    elif token == "USDT":
        url = f"https://apilist.tronscanapi.com/api/transfer/trc20?address={address}&trc20Id=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t&limit=10"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    transfers = data.get("token_transfers", [])
                    if not isinstance(transfers, list):
                        return None

                    for tr in transfers:
                        to_addr = tr.get("to_address", "")
                        raw_amount = float(tr.get("amount_str", 0)) / 1_000_000.0
                        txid = tr.get("transaction_id", "")
                        confirmed = tr.get("confirmed", False)

                        if to_addr == address and abs(raw_amount - expected_amount) <= 0.05:
                            return {
                                "found": True,
                                "confirmed": confirmed,
                                "txid": txid,
                                "amount": raw_amount,
                                "token": "USDT",
                                "explorer_url": f"https://tronscan.org/#/transaction/{txid}"
                            }
        except Exception as e:
            logger.error(f"Error checking USDT TRC-20 for {address}: {e}")
            return None

    # 4. Solana (SOL) Check via Public Solana RPC
    elif token == "SOL":
        rpc_url = "https://api.mainnet-beta.solana.com"
        headers = {"Content-Type": "application/json"}
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [address, {"limit": 5}]
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(rpc_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    signatures = data.get("result", [])
                    if not isinstance(signatures, list):
                        return None

                    for sig_info in signatures[:3]:
                        sig = sig_info.get("signature")
                        if not sig or sig_info.get("err") is not None:
                            continue

                        tx_payload = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "getTransaction",
                            "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                        }
                        async with session.post(rpc_url, json=tx_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as tx_resp:
                            if tx_resp.status == 200:
                                tx_data = await tx_resp.json()
                                result = tx_data.get("result")
                                if result and "meta" in result:
                                    meta = result["meta"]
                                    pre_balances = meta.get("preBalances", [])
                                    post_balances = meta.get("postBalances", [])
                                    account_keys = result.get("transaction", {}).get("message", {}).get("accountKeys", [])

                                    for idx, acc in enumerate(account_keys):
                                        pubkey = acc if isinstance(acc, str) else acc.get("pubkey", "")
                                        if pubkey.lower() == address.lower() and idx < len(pre_balances) and idx < len(post_balances):
                                            diff_lamports = post_balances[idx] - pre_balances[idx]
                                            if diff_lamports > 0:
                                                sol_val = round(diff_lamports / 1_000_000_000.0, 4)
                                                if abs(sol_val - expected_amount) <= 0.001:
                                                    return {
                                                        "found": True,
                                                        "confirmed": True,
                                                        "txid": sig,
                                                        "amount": sol_val,
                                                        "token": "SOL",
                                                        "explorer_url": f"https://solscan.io/tx/{sig}"
                                                    }
        except Exception as e:
            logger.error(f"Error checking SOL blockchain for {address}: {e}")
            return None

    return None

