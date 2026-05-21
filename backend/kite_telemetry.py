import time

# pyrefly: ignore [missing-import]
from kiteconnect import KiteConnect

# Import auth and utils modules
from kite_auth_manager import get_kite_client
from kite_utils import handle_auth_failure

# Global cache to prevent hitting Zerodha positions rate limit too frequently
_positions_cache = None
_positions_cache_time = 0.0

def get_kite_margin():
    """
    Reads the available equity live balance (buying power) from the Zerodha account.
    Returns:
        dict: Containing human-readable margins (net, cash, collateral) or None if unavailable.
    """
    try:
        kite = get_kite_client()
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
        handle_auth_failure(e)
        return None

def get_kite_orders():
    """
    Reads the active and historical order log from Zerodha.
    Returns:
        list: Formatted dict representation of orders, newest first.
    """
    try:
        kite = get_kite_client()
        orders = kite.orders()
        formatted_orders = []
        # Reverse the list so the most recent orders appear first in the logs/UI
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
                "status_message": o.get("status_message") or "",
                "variety": o.get("variety") or "regular"
            })
        return formatted_orders
    except Exception as e:
        print(f"Error fetching Kite orders: {e}")
        handle_auth_failure(e)
        return []

def get_kite_positions(force=False):
    """
    Reads net open positions from Zerodha (cached for 10 seconds to avoid API throttling).
    Returns:
        list: List of open position details.
    """
    global _positions_cache, _positions_cache_time
    now = time.time()
    
    # Return cached data if request is within 10 seconds window and not forced
    if not force and _positions_cache is not None and (now - _positions_cache_time) < 10.0:
        return _positions_cache
        
    try:
        kite = get_kite_client()
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
        handle_auth_failure(e)
        return []
