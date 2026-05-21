import os
import json
import time
from kiteconnect import KiteConnect

# Import auth and utils modules
from kite_auth_manager import get_kite_client
from kite_utils import round_to_tick, handle_auth_failure

# Global cache to prevent hitting Zerodha positions rate limit too frequently
_positions_cache = None
_positions_cache_time = 0.0

def get_kite_margin():
    """
    Fetches the available equity live balance (buying power) from the Zerodha account.
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
    Fetches the active and historical order log from Zerodha.
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
                "status_message": o.get("status_message") or ""
            })
        return formatted_orders
    except Exception as e:
        print(f"Error fetching Kite orders: {e}")
        handle_auth_failure(e)
        return []

def get_kite_positions(force=False):
    """
    Fetches net open positions from Zerodha (cached for 10 seconds to avoid API throttling).
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

def place_marketable_limit_exit(kite, exchange, symbol, tx_type, quantity, product, last_price=None):
    """
    Submits a marketable LIMIT order to square off a position immediately.
    Uses a 0.5% protective buffer over the last price (LTP) to ensure instant matching
    at the best bid/ask, while protecting against sudden spread spikes.
    """
    try:
        # If no last price is supplied, fetch it live from LTP endpoint
        if last_price is None or last_price <= 0:
            ltp_key = f"{exchange}:{symbol}"
            ltp_data = kite.ltp(ltp_key)
            last_price = ltp_data.get(ltp_key, {}).get("last_price")
            if not last_price:
                raise ValueError(f"Could not retrieve last price for {ltp_key}")

        # BUY exit needs a higher limit (1.005), SELL exit needs a lower limit (0.995) to fill instantly
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
    Modifies an existing stop-loss (SL) order trigger price or places a new one if not present.
    Enforces NSE tick size increments. Matches trigger price and limit price to avoid slippage.
    """
    try:
        kite = get_kite_client()
        rounded_price = round_to_tick(new_trigger_price)
        limit_price = rounded_price
        
        if sl_order_id:
            # Modify existing stop loss order
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
            # Check mandatory fields for placement
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
        handle_auth_failure(e)
        return {"status": "error", "message": str(e)}

def panic_square_off():
    """
    Initiates an emergency cancel of all pending orders and places marketable limit orders
    to exit all active net positions immediately.
    """
    try:
        kite = get_kite_client()
        summary = {
            "cancelled_orders": 0,
            "squared_positions": 0,
            "errors": []
        }
        
        # 1. Cancel all open/pending orders
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
            
        # 2. Square off all active net positions
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
        handle_auth_failure(e)
        return {"status": "error", "message": f"Panic failed: {e}"}

def exit_single_position(symbol):
    """
    Exits a single symbol's position by canceling its open orders and placing a marketable
    limit exit order.
    """
    try:
        kite = get_kite_client()
        
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
            
        # 2. Square off position
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
        handle_auth_failure(e)
        return {"status": "error", "message": f"Exit failed for {symbol}: {e}"}

def book_half_position(symbol):
    """
    Reduces the position size by 50% (taking profit) and modifies corresponding
    pending SL and target orders to match the remaining quantity.
    """
    try:
        kite = get_kite_client()
        
        # 1. Retrieve the position info
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
        
        # Calculate booking and residual sizing
        half_qty = max(1, abs(qty) // 2)
        remaining_qty = abs(qty) - half_qty
        exit_tx_type = "SELL" if qty > 0 else "BUY"
        
        # 2. Square off 50% of the position
        place_marketable_limit_exit(kite, exchange, symbol, exit_tx_type, half_qty, product,
                                    last_price=target_pos.get("last_price", 0.0))
        
        refactored_orders = []
        cancelled_orders = 0
        
        # 3. Modify pending SL and Limit orders to reflect new position size
        if remaining_qty == 0:
            # If no remaining qty, cancel all open orders
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
            # Modify target and SL orders to match remaining_qty
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
        handle_auth_failure(e)
        return {"status": "error", "message": f"Scale-out failed for {symbol}: {e}"}
