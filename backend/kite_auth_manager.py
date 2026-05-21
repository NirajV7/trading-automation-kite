import os
import json
import time
import urllib.request
from datetime import datetime
from kiteconnect import KiteConnect

# Import configuration settings
from config import (
    KITE_TOKEN_FILE,
    KITE_API_KEY,
    KITE_API_SECRET,
    KITE_REDIRECT_URL,
)

# Whitelisted IPs for Zerodha connection audits
KITE_WHITELISTED_IPS = [
    "2401:4900:883a:fb23:799d:9a4b:4b9d:11ba",
    "2409:40f2:3a:8df0:c4a2:bd76:cea3:b353"
]

def get_tick_size(price):
    """Calculates the dynamic NSE tick size based on the stock's price range."""
    if price < 250:
        return 0.01
    elif price <= 1000:
        return 0.05
    elif price <= 5000:
        return 0.10
    elif price <= 10000:
        return 0.50
    elif price <= 20000:
        return 1.00
    else:
        return 5.00

def round_to_tick(price, tick_size=None):
    """Rounds a price to the nearest tick size increment to prevent Zerodha order rejections."""
    if tick_size is None:
        tick_size = get_tick_size(price)
    return round(round((price + 1e-9) / tick_size) * tick_size, 2)

def check_kite_auth():
    """Validates local Kite token. Returns (needs_login, auth_url)."""
    def get_new_url():
        return f"https://kite.zerodha.com/connect/login?api_key={KITE_API_KEY}&v=3"

    if not KITE_API_KEY or not KITE_API_SECRET:
        print("⚠️ Missing KITE_API_KEY or KITE_API_SECRET in config/environment.")
        return True, "#"

    if os.path.exists(KITE_TOKEN_FILE):
        with open(KITE_TOKEN_FILE, "r") as f:
            try:
                token_data = json.load(f)
                token_date_str = token_data.get("date")
                if token_date_str:
                    try:
                        token_date = datetime.strptime(token_date_str, "%Y-%m-%d").date()
                        today = datetime.now().date()
                        # Force daily refresh only if we crossed into a new day AND it is past 6:00 AM IST
                        if token_date != today and datetime.now().hour >= 6:
                            return True, get_new_url()
                    except Exception as e:
                        print(f"Kite date check fallback error: {e}")
                        return True, get_new_url()
                else:
                    return True, get_new_url()
                
                access_token = token_data.get("access_token")
                if not access_token:
                    return True, get_new_url()
                
                return False, None
            except Exception as e:
                print(f"Kite Auth Check Error: {e}")
                return True, get_new_url()
                
    return True, get_new_url()

def exchange_kite_token(request_token):
    """Exchanges a Kite request_token for an access_token and caches it."""
    if not request_token:
        return False, "Request token cannot be empty"
        
    try:
        kite = KiteConnect(api_key=KITE_API_KEY)
        data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        access_token = data.get("access_token")
        
        if access_token:
            with open(KITE_TOKEN_FILE, "w") as f:
                json.dump({
                    "access_token": access_token,
                    "date": datetime.now().strftime("%Y-%m-%d")
                }, f)
            return True, "Authorized Kite Connect successfully!"
        return False, "Failed to retrieve access token from session data."
    except Exception as e:
        return False, f"Exception during Kite token exchange: {str(e)}"

def _handle_auth_failure(e):
    """Helper to detect auth failures and clean up token file dynamically."""
    try:
        import kiteconnect.exceptions as ex
        is_auth_err = False
        if isinstance(e, (ex.TokenException, ex.PermissionException)):
            is_auth_err = True
        else:
            err_msg = str(e).lower()
            if "incorrect" in err_msg or "token" in err_msg or "auth" in err_msg or "api_key" in err_msg:
                is_auth_err = True
                
        if is_auth_err:
            print("⚠️ [Kite Auth] Stale or invalid session token detected. Deleting cached token to trigger re-auth.")
            if os.path.exists(KITE_TOKEN_FILE):
                os.remove(KITE_TOKEN_FILE)
    except Exception as helper_err:
        print(f"⚠️ [Kite Auth] Error in auth failure handler: {helper_err}")

def get_kite_margin():
    """Fetches the available equity live balance (buying power). Returns dict or None."""
    if not KITE_API_KEY:
        return None
    if os.path.exists(KITE_TOKEN_FILE):
        with open(KITE_TOKEN_FILE, "r") as f:
            try:
                token_data = json.load(f)
                access_token = token_data.get("access_token")
                if access_token:
                    kite = KiteConnect(api_key=KITE_API_KEY)
                    kite.set_access_token(access_token)
                    margins = kite.margins("equity")
                    
                    net_usable = margins.get("net", 0.0)
                    cash = margins.get("available", {}).get("live_balance", 0.0)
                    collateral = margins.get("available", {}).get("collateral", 0.0)
                    
                    return {
                        "net": f"₹{net_usable:,.2f}",
                        "cash": f"₹{cash:,.2f}",
                        "collateral": f"₹{collateral:,.2f}"
                    }
            except Exception as e:
                print(f"Error fetching Kite margin: {e}")
                _handle_auth_failure(e)
                return None
    return None

def get_kite_orders():
    """Fetches list of live orders from Zerodha Kite."""
    if not KITE_API_KEY:
        return []
    if os.path.exists(KITE_TOKEN_FILE):
        with open(KITE_TOKEN_FILE, "r") as f:
            try:
                token_data = json.load(f)
                access_token = token_data.get("access_token")
                if access_token:
                    kite = KiteConnect(api_key=KITE_API_KEY)
                    kite.set_access_token(access_token)
                    orders = kite.orders()
                    # Return latest orders first (reversed)
                    formatted_orders = []
                    for o in reversed(orders):
                        formatted_orders.append({
                            "order_id": o.get("order_id"),
                            "symbol": o.get("tradingsymbol"),
                            "transaction_type": o.get("transaction_type"),
                            "quantity": o.get("quantity"),
                            "order_type": o.get("order_type"),
                            "status": o.get("status"),
                            "price": o.get("price"),
                            "trigger_price": o.get("trigger_price"),
                            "status_message": o.get("status_message") or ""
                        })
                    return formatted_orders
            except Exception as e:
                print(f"Error fetching Kite orders: {e}")
                _handle_auth_failure(e)
                return []
    return []

_positions_cache = None
_positions_cache_time = 0.0

def get_kite_positions(force=False):
    """Fetches list of active day & net positions from Zerodha Kite (cached for 10 seconds)."""
    global _positions_cache, _positions_cache_time
    if not KITE_API_KEY:
        return []
        
    now = time.time()
    if not force and _positions_cache is not None and (now - _positions_cache_time) < 10.0:
        return _positions_cache
        
    if os.path.exists(KITE_TOKEN_FILE):
        with open(KITE_TOKEN_FILE, "r") as f:
            try:
                token_data = json.load(f)
                access_token = token_data.get("access_token")
                if access_token:
                    kite = KiteConnect(api_key=KITE_API_KEY)
                    kite.set_access_token(access_token)
                    positions = kite.positions()
                    net_positions = positions.get("net", [])
                    
                    formatted_positions = []
                    for p in net_positions:
                        formatted_positions.append({
                            "symbol": p.get("tradingsymbol"),
                            "quantity": p.get("quantity"),
                            "average_price": p.get("average_price"),
                            "last_price": p.get("last_price"),
                            "pnl": p.get("pnl"),
                            "product": p.get("product"),
                            "buy_value": p.get("buy_value", 0.0),
                            "sell_value": p.get("sell_value", 0.0),
                            "buy_quantity": p.get("buy_quantity", 0),
                            "sell_quantity": p.get("sell_quantity", 0),
                            "buy_price": p.get("buy_price", 0.0),
                            "sell_price": p.get("sell_price", 0.0)
                        })
                    _positions_cache = formatted_positions
                    _positions_cache_time = now
                    return formatted_positions
            except Exception as e:
                print(f"Error fetching Kite positions: {e}")
                _handle_auth_failure(e)
                return []
    return []

def place_marketable_limit_exit(kite, exchange, symbol, tx_type, quantity, product, last_price=None):
    """
    Submits a marketable LIMIT order to square off positions.
    Uses provided last_price (from position data) to avoid kite.ltp() permission issues.
    Applies a 0.5% protective buffer so the limit fills instantly.
    """
    try:
        if last_price is None or last_price <= 0:
            ltp_key = f"{exchange}:{symbol}"
            ltp_data = kite.ltp(ltp_key)
            last_price = ltp_data.get(ltp_key, {}).get("last_price")
            if not last_price:
                raise ValueError(f"Could not retrieve last price for {ltp_key}")

        # Apply 0.5% protection buffer for instant fill, using dynamic NSE tick size
        if tx_type == "SELL":
            limit_price = round_to_tick(last_price * 0.995)
        else:
            limit_price = round_to_tick(last_price * 1.005)

        return kite.place_order(
            variety="regular",
            exchange=exchange,
            tradingsymbol=symbol,
            transaction_type=tx_type,
            quantity=quantity,
            product=product,
            order_type="LIMIT",
            price=limit_price
        )
    except Exception as e:
        print(f"⚠️ [MARKETABLE LIMIT EXIT] Failed for {symbol}: {e}")
        raise

def modify_or_place_sl(symbol, new_trigger_price, sl_order_id=None, quantity=None, transaction_type=None, product=None):
    """
    Modify an existing SL order's trigger price, or place a new SL order if none exists.
    trigger_price is rounded to the correct NSE tick size based on price level.
    """
    if not KITE_API_KEY or not os.path.exists(KITE_TOKEN_FILE):
        return {"status": "error", "message": "Kite not authenticated"}
    
    with open(KITE_TOKEN_FILE, "r") as f:
        try:
            token_data = json.load(f)
            access_token = token_data.get("access_token")
            if not access_token:
                return {"status": "error", "message": "No access token found"}
            
            kite = KiteConnect(api_key=KITE_API_KEY)
            kite.set_access_token(access_token)
            
            # Round to correct NSE tick size (dynamic based on price level)
            rounded_price = round_to_tick(new_trigger_price)
            limit_price = rounded_price
            
            if sl_order_id:
                # Modify existing SL order
                kite.modify_order(
                    variety="regular",
                    order_id=sl_order_id,
                    order_type="SL",
                    trigger_price=rounded_price,
                    price=limit_price
                )
                print(f"✅ [SL MODIFY] {symbol}: SL moved to ₹{rounded_price} (limit ₹{limit_price})")
                return {"status": "success", "message": f"SL modified to ₹{rounded_price}", "new_sl": rounded_price}
            else:
                # Place new SL limit order
                if not quantity or not transaction_type or not product:
                    return {"status": "error", "message": "Missing quantity/transaction_type/product for new SL order"}
                
                order_id = kite.place_order(
                    variety="regular",
                    exchange="NSE",
                    tradingsymbol=symbol,
                    transaction_type=transaction_type,
                    quantity=abs(quantity),
                    product=product,
                    order_type="SL",
                    trigger_price=rounded_price,
                    price=limit_price
                )
                print(f"✅ [SL PLACED] {symbol}: New SL at ₹{rounded_price} (limit ₹{limit_price})")
                return {"status": "success", "message": f"New SL placed at ₹{rounded_price}", "new_sl": rounded_price, "order_id": order_id}
                
        except Exception as e:
            print(f"❌ [SL ERROR] {symbol}: {e}")
            _handle_auth_failure(e)
            return {"status": "error", "message": str(e)}

def panic_square_off():
    """Cancels all pending orders and market-closes all active positions on Zerodha Kite."""
    if not KITE_API_KEY:
        return {"status": "error", "message": "API key not configured"}
        
    if not os.path.exists(KITE_TOKEN_FILE):
        return {"status": "error", "message": "No active Kite session"}
        
    with open(KITE_TOKEN_FILE, "r") as f:
        try:
            token_data = json.load(f)
            access_token = token_data.get("access_token")
            if not access_token:
                return {"status": "error", "message": "Access token missing in token file"}
                
            kite = KiteConnect(api_key=KITE_API_KEY)
            kite.set_access_token(access_token)
            
            summary = {
                "cancelled_orders": 0,
                "squared_positions": 0,
                "errors": []
            }
            
            # 1. Fetch and cancel all open/pending orders
            try:
                orders = kite.orders()
                open_statuses = ["OPEN", "TRIGGER PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED"]
                for o in orders:
                    if o.get("status") in open_statuses:
                        try:
                            kite.cancel_order(variety=o.get("variety"), order_id=o.get("order_id"))
                            summary["cancelled_orders"] += 1
                        except Exception as e:
                            summary["errors"].append(f"Cancel order {o.get('order_id')} failed: {e}")
            except Exception as e:
                summary["errors"].append(f"Fetch orders failed: {e}")
                
            # 2. Fetch and market-square off all active net positions
            try:
                positions = kite.positions()
                net_positions = positions.get("net", [])
                for p in net_positions:
                    qty = p.get("quantity", 0)
                    if qty != 0:
                        symbol = p.get("tradingsymbol")
                        exchange = p.get("exchange")
                        product = p.get("product")
                        
                        tx_type = "SELL" if qty > 0 else "BUY"
                        exit_qty = abs(qty)
                        
                        try:
                            place_marketable_limit_exit(kite, exchange, symbol, tx_type, exit_qty, product,
                                                        last_price=p.get("last_price", 0.0))
                            summary["squared_positions"] += 1
                        except Exception as e:
                            summary["errors"].append(f"Square off {symbol} failed: {e}")
            except Exception as e:
                summary["errors"].append(f"Fetch positions failed: {e}")
                
            if summary["errors"]:
                return {
                    "status": "partial",
                    "message": f"Panic complete with errors. Cancelled: {summary['cancelled_orders']}, Squared: {summary['squared_positions']}",
                    "details": summary
                }
            return {
                "status": "success",
                "message": f"Successfully cancelled {summary['cancelled_orders']} orders and squared off {summary['squared_positions']} positions.",
                "details": summary
            }
            
        except Exception as e:
            return {"status": "error", "message": f"Panic failed: {e}"}

def exit_single_position(symbol):
    """Cancels pending orders for the symbol and market-squares off its active position on Zerodha Kite."""
    if not KITE_API_KEY:
        return {"status": "error", "message": "API key not configured"}
    if not os.path.exists(KITE_TOKEN_FILE):
        return {"status": "error", "message": "No active Kite session"}
        
    with open(KITE_TOKEN_FILE, "r") as f:
        try:
            token_data = json.load(f)
            access_token = token_data.get("access_token")
            if not access_token:
                return {"status": "error", "message": "Access token missing"}
                
            kite = KiteConnect(api_key=KITE_API_KEY)
            kite.set_access_token(access_token)
            
            # 1. Cancel pending orders for this symbol
            cancelled = 0
            try:
                orders = kite.orders()
                open_statuses = ["OPEN", "TRIGGER PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED"]
                for o in orders:
                    if o.get("tradingsymbol") == symbol and o.get("status") in open_statuses:
                        kite.cancel_order(variety=o.get("variety"), order_id=o.get("order_id"))
                        cancelled += 1
            except Exception as e:
                print(f"Cancel orders for {symbol} failed: {e}")
                
            # 2. Square off net positions for this symbol
            squared = False
            positions = kite.positions()
            net_positions = positions.get("net", [])
            for p in net_positions:
                if p.get("tradingsymbol") == symbol:
                    qty = p.get("quantity", 0)
                    if qty != 0:
                        exchange = p.get("exchange")
                        product = p.get("product")
                        tx_type = "SELL" if qty > 0 else "BUY"
                        exit_qty = abs(qty)
                        
                        place_marketable_limit_exit(kite, exchange, symbol, tx_type, exit_qty, product,
                                                    last_price=p.get("last_price", 0.0))
                        squared = True
                        break
            
            return {
                "status": "success",
                "message": f"Exit completed for {symbol}. Orders cancelled: {cancelled}, Position squared: {squared}"
            }
        except Exception as e:
            return {"status": "error", "message": f"Exit failed for {symbol}: {e}"}

def book_half_position(symbol):
    """Squares off exactly 50% of the position and refactors corresponding pending SL and Target orders."""
    if not KITE_API_KEY:
        return {"status": "error", "message": "API key not configured"}
    if not os.path.exists(KITE_TOKEN_FILE):
        return {"status": "error", "message": "No active Kite session"}
        
    with open(KITE_TOKEN_FILE, "r") as f:
        try:
            token_data = json.load(f)
            access_token = token_data.get("access_token")
            if not access_token:
                return {"status": "error", "message": "Access token missing"}
                
            kite = KiteConnect(api_key=KITE_API_KEY)
            kite.set_access_token(access_token)
            
            # 1. Fetch active net positions
            positions = kite.positions()
            net_positions = positions.get("net", [])
            target_pos = None
            for p in net_positions:
                if p.get("tradingsymbol") == symbol:
                    target_pos = p
                    break
                    
            if not target_pos:
                return {"status": "error", "message": f"No active position found for {symbol}"}
                
            qty = target_pos.get("quantity", 0)
            if qty == 0:
                return {"status": "error", "message": f"Position for {symbol} is already closed"}
                
            exchange = target_pos.get("exchange")
            product = target_pos.get("product")
            
            # Calculate booking size
            half_qty = max(1, abs(qty) // 2)
            remaining_qty = abs(qty) - half_qty
            
            # Direction to exit half
            exit_tx_type = "SELL" if qty > 0 else "BUY"
            
            # 2. Place marketable limit order to square off 50% — pass last_price from position data
            place_marketable_limit_exit(kite, exchange, symbol, exit_tx_type, half_qty, product,
                                        last_price=target_pos.get("last_price", 0.0))
            
            refactored_orders = []
            cancelled_orders = 0
            
            # 3. Handle refactoring of SL and Target orders
            if remaining_qty == 0:
                # If no remaining qty, cancel all open orders for this symbol
                try:
                    orders = kite.orders()
                    open_statuses = ["OPEN", "TRIGGER PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED"]
                    for o in orders:
                        if o.get("tradingsymbol") == symbol and o.get("status") in open_statuses:
                            kite.cancel_order(variety=o.get("variety"), order_id=o.get("order_id"))
                            cancelled_orders += 1
                except Exception as e:
                    print(f"Cancel orders for {symbol} scale-out fallback failed: {e}")
            else:
                # We have a remaining quantity. Refactor open SL and Target orders.
                try:
                    orders = kite.orders()
                    open_statuses = ["OPEN", "TRIGGER PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED"]
                    for o in orders:
                        if o.get("tradingsymbol") == symbol and o.get("status") in open_statuses:
                            if o.get("transaction_type") == exit_tx_type:
                                otype = o.get("order_type")
                                if otype in ["SL", "SL-M", "LIMIT"]:
                                    mod_params = {
                                        "variety": o.get("variety", "regular"),
                                        "order_id": o.get("order_id"),
                                        "quantity": remaining_qty,
                                        "order_type": otype
                                    }
                                    if otype in ["LIMIT", "SL"]:
                                        mod_params["price"] = o.get("price")
                                    if otype in ["SL", "SL-M"]:
                                        mod_params["trigger_price"] = o.get("trigger_price")
                                        
                                    kite.modify_order(**mod_params)
                                    refactored_orders.append(f"{o.get('order_id')} ({otype})")
                except Exception as e:
                    print(f"Refactoring orders for {symbol} failed: {e}")
                    
            msg = f"Booked 50% ({half_qty} shares) for {symbol}."
            if remaining_qty == 0:
                msg += f" Full exit completed. Cancelled {cancelled_orders} pending orders."
            else:
                msg += f" Remaining size: {remaining_qty}. Refactored {len(refactored_orders)} orders: {', '.join(refactored_orders)}."
                
            return {
                "status": "success",
                "message": msg
            }
        except Exception as e:
            return {"status": "error", "message": f"Scale-out failed for {symbol}: {e}"}

def get_public_ip():
    """Fetches public IPv4 and IPv6 addresses and checks them against whitelisted IPs."""
    ipv4 = None
    ipv6 = None
    
    # Fetch IPv4
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=1.0) as response:
            ipv4 = response.read().decode("utf-8").strip()
    except Exception:
        pass
        
    # Fetch IPv6
    try:
        with urllib.request.urlopen("https://api6.ipify.org", timeout=1.0) as response:
            ipv6 = response.read().decode("utf-8").strip()
    except Exception:
        pass

    # Match check
    is_whitelisted = False
    matched_ip = None
    
    if ipv4 and ipv4 in KITE_WHITELISTED_IPS:
        is_whitelisted = True
        matched_ip = ipv4
    elif ipv6 and ipv6 in KITE_WHITELISTED_IPS:
        is_whitelisted = True
        matched_ip = ipv6
        
    return {
        "ipv4": ipv4 or "Offline/Unavailable",
        "ipv6": ipv6 or "Offline/Unavailable",
        "is_whitelisted": is_whitelisted,
        "matched_ip": matched_ip
    }
