import os
import time
import hmac
import hashlib
import logging
import argparse
from urllib.parse import urlencode
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")


# Try to import the Binance futures connector; if not available we'll use raw requests
USE_CONNECTOR = True
try:
    from binance.um_futures import UMFutures
except Exception:
    USE_CONNECTOR = False

import requests
from getpass import getpass
from typing import Optional, Dict, Any

# ---- Configuration ----
TESTNET_BASE = "https://testnet.binancefuture.com"
  # official testnet base URL
LOGFILE = "bot.log"
RECV_WINDOW = 5000  # ms


# ---- Logging ----
logger = logging.getLogger("BinanceFuturesBot")
logger.setLevel(logging.DEBUG)
fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
fh = logging.FileHandler(LOGFILE)
fh.setFormatter(fmt)
fh.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setFormatter(fmt)
ch.setLevel(logging.INFO)
logger.addHandler(fh)
logger.addHandler(ch)


# ---- Utilities ----
def get_api_credentials(api_key: Optional[str], api_secret: Optional[str]):
    a = api_key or os.getenv("BINANCE_API_KEY")
    s = api_secret or os.getenv("BINANCE_API_SECRET")
    if not a:
        a = input("Enter BINANCE API KEY (or set BINANCE_API_KEY env): ").strip()
    if not s:
        # ask securely
        s = getpass("Enter BINANCE API SECRET (or set BINANCE_API_SECRET env): ").strip()
    if not a or not s:
        raise SystemExit("API key and secret are required.")
    return a, s


def sign_payload(query_string: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


# ---- Raw REST functions (signed) ----
def raw_post_order(api_key: str, api_secret: str, params: Dict[str, Any], base_url=TESTNET_BASE):
    """
    POST /fapi/v1/order (signed)
    Uses form body and header X-MBX-APIKEY
    """
    params = dict(params)  # copy
    params["timestamp"] = int(time.time() * 1000)
    params.setdefault("recvWindow", RECV_WINDOW)
    qs = urlencode(params)
    signature = sign_payload(qs, api_secret)
    params["signature"] = signature
    headers = {"X-MBX-APIKEY": api_key}
    url = base_url.rstrip("/") + "/fapi/v1/order"
    logger.debug("POST %s  params=%s", url, params)
    r = requests.post(url, headers=headers, data=params, timeout=10)
    try:
        j = r.json()
    except Exception:
        logger.error("Non-JSON response: %s", r.text)
        r.raise_for_status()
    logger.info("Order response: %s", j)
    r.raise_for_status()
    return j


def raw_get(endpoint: str, api_key: Optional[str] = None, params: Dict[str, Any] = None, api_secret: Optional[str] = None, signed=False, base_url=TESTNET_BASE):
    params = dict(params or {})
    headers = {}
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params.setdefault("recvWindow", RECV_WINDOW)
        qs = urlencode(params)
        signature = sign_payload(qs, api_secret)
        params["signature"] = signature
    if api_key:
        headers["X-MBX-APIKEY"] = api_key
    url = base_url.rstrip("/") + endpoint
    logger.debug("GET %s params=%s", url, params)
    r = requests.get(url, headers=headers, params=params, timeout=10)
    j = r.json()
    logger.debug("GET response: %s", j)
    r.raise_for_status()
    return j


# ---- Connector wrapper ----
class BinanceFuturesBot:
    def __init__(self, api_key: str, api_secret: str, use_connector: bool = USE_CONNECTOR):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = TESTNET_BASE
        self.use_connector = use_connector and USE_CONNECTOR
        if self.use_connector:
            try:
                self.client = UMFutures(key=self.api_key, secret=self.api_secret, base_url=self.base_url)
                logger.info("Using binance-futures-connector (UMFutures).")
            except Exception as e:
                logger.exception("Connector init failed, falling back to raw REST. Error: %s", e)
                self.use_connector = False
                self.client = None
        else:
            logger.info("Using raw REST (requests). Connector not available.")

    def get_server_time(self):
        if self.use_connector:
            return self.client.time()
        else:
            return raw_get("/fapi/v1/time")

    def get_price(self, symbol: str):
        symbol = symbol.upper()
        if self.use_connector:
            return self.client.ticker_price(symbol=symbol)
        else:
            return raw_get("/fapi/v1/ticker/price", params={"symbol": symbol})

    def get_balance(self):
        if self.use_connector:
            return self.client.balance()
        else:
            return raw_get("/fapi/v2/balance", api_key=self.api_key, api_secret=self.api_secret, signed=True)

    def place_order(self, symbol: str, side: str, order_type: str, quantity: float = None, price: float = None, time_in_force: str = "GTC", reduce_only: bool = False, close_position: bool = False):
        symbol = symbol.upper()
        side = side.upper()
        order_type = order_type.upper()
        params = {"symbol": symbol, "side": side, "type": order_type}
        if reduce_only:
            params["reduceOnly"] = True
        if close_position:
            params["reduceOnly"] = True  # for close on certain endpoints, using reduceOnly as safety

        # validation
        if order_type == "MARKET":
            if quantity is None:
                raise ValueError("MARKET orders require quantity.")
            params["quantity"] = float(quantity)
        elif order_type == "LIMIT":
            if price is None or quantity is None:
                raise ValueError("LIMIT orders require price and quantity.")
            params["price"] = str(price)
            params["quantity"] = float(quantity)
            params["timeInForce"] = time_in_force
        else:
            # You can expand to STOP, STOP_MARKET, TAKE_PROFIT etc.
            raise ValueError("Only MARKET and LIMIT supported in this simple bot.")

        logger.info("Placing order: %s", params)
        if self.use_connector:
            return self.client.new_order(**params)
        else:
            return raw_post_order(self.api_key, self.api_secret, params)

    def cancel_order(self, symbol: str, order_id: int = None, origClientOrderId: str = None):
        # cancel endpoint: DELETE /fapi/v1/order
        params = {"symbol": symbol.upper()}
        if order_id:
            params["orderId"] = int(order_id)
        if origClientOrderId:
            params["origClientOrderId"] = origClientOrderId
        if self.use_connector:
            return self.client.cancel_order(**params)
        else:
            endpoint = "/fapi/v1/order"
            # For DELETE with signature the signature should be on query string
            params["timestamp"] = int(time.time() * 1000)
            params.setdefault("recvWindow", RECV_WINDOW)
            qs = urlencode(params)
            signature = sign_payload(qs, self.api_secret)
            params["signature"] = signature
            headers = {"X-MBX-APIKEY": self.api_key}
            url = self.base_url.rstrip("/") + endpoint
            r = requests.delete(url, headers=headers, params=params, timeout=10)
            j = r.json()
            logger.info("Cancel response: %s", j)
            r.raise_for_status()
            return j


# ---- CLI ----
def main():
    parser = argparse.ArgumentParser(description="Simple Binance Futures Testnet Bot (USDT-M)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # price
    p_price = sub.add_parser("price", help="Get current symbol price")
    p_price.add_argument("--symbol", required=True)

    # balance
    p_bal = sub.add_parser("balance", help="Get account balance")

    # place-order
    p_place = sub.add_parser("place-order", help="Place an order")
    p_place.add_argument("--symbol", required=True)
    p_place.add_argument("--side", required=True, choices=["BUY", "SELL"])
    p_place.add_argument("--type", required=True, choices=["MARKET", "LIMIT"])
    p_place.add_argument("--quantity", type=float, required=False)
    p_place.add_argument("--price", type=float, required=False)
    p_place.add_argument("--reduce-only", action="store_true")
    p_place.add_argument("--close-position", action="store_true")

    # cancel
    p_cancel = sub.add_parser("cancel-order", help="Cancel an order")
    p_cancel.add_argument("--symbol", required=True)
    p_cancel.add_argument("--order-id", type=int, required=False)
    p_cancel.add_argument("--client-order-id", required=False)

    # credentials / optional
    parser.add_argument("--api-key", required=False)
    parser.add_argument("--api-secret", required=False)
    parser.add_argument("--no-connector", action="store_true", help="Force raw REST mode instead of connector")

    args = parser.parse_args()

    api_key, api_secret = get_api_credentials(args.api_key, args.api_secret)
    bot = BinanceFuturesBot(api_key, api_secret, use_connector=not args.no_connector)

    try:
        if args.cmd == "price":
            r = bot.get_price(args.symbol)
            print("PRICE:", r)
        elif args.cmd == "balance":
            r = bot.get_balance()
            print("BALANCE:", r)
        elif args.cmd == "place-order":
            res = bot.place_order(
                symbol=args.symbol,
                side=args.side,
                order_type=args.type,
                quantity=args.quantity,
                price=args.price,
                reduce_only=args.reduce_only,
                close_position=args.close_position,
            )
            print("ORDER RESULT:", res)
        elif args.cmd == "cancel-order":
            res = bot.cancel_order(symbol=args.symbol, order_id=args.order_id, origClientOrderId=args.client_order_id)
            print("CANCEL RESULT:", res)
    except Exception as e:
        logger.exception("Error while running command: %s", e)
        print("ERROR:", str(e))


if __name__ == "__main__":
    main()































    
