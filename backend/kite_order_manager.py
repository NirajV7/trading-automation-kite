import os
import time

# pyrefly: ignore [missing-import]
from kiteconnect import KiteConnect

# Import auth and utils modules
from kite_auth_manager import get_kite_client
from kite_utils import round_to_tick, get_tick_size, handle_auth_failure

OPEN_ORDER_STATUSES = {"OPEN", "TRIGGER PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED", "OPEN PENDING"}
FAILED_ORDER_STATUSES = {"REJECTED", "CANCELLED"}


def get_buffered_sl_prices(trigger_price, transaction_type):
    """Returns rounded trigger and buffered SL-limit price for the exit direction."""
    trigger = round_to_tick(trigger_price)
    tick_size = get_tick_size(trigger)
    buffer_value = max(2 * tick_size, trigger * 0.0015)

    if transaction_type == "SELL":
        raw_limit = trigger - buffer_value
        limit_price = round_to_tick(raw_limit, tick_size)
        if limit_price >= trigger:
            limit_price = round_to_tick(trigger - tick_size, tick_size)
    else:
        raw_limit = trigger + buffer_value
        limit_price = round_to_tick(raw_limit, tick_size)
        if limit_price <= trigger:
            limit_price = round_to_tick(trigger + tick_size, tick_size)

    return trigger, limit_price


def get_latest_order_state(kite, order_id):
    """Fetches latest order state from order_history first, then orderbook fallback."""
    try:
        history = kite.order_history(order_id)
        if history:
            return history[-1]
    except Exception:
        pass

    try:
        for order in kite.orders():
            if order.get("order_id") == order_id:
                return order
    except Exception:
        pass
    return None


def wait_for_order_completion(kite, order_id, timeout=10.0, poll_interval=0.5):
    """Waits for a Kite order to reach COMPLETE or a terminal failed state."""
    deadline = time.time() + timeout
    last_state = None
    while time.time() < deadline:
        last_state = get_latest_order_state(kite, order_id)
        status = (last_state or {}).get("status")
        if status == "COMPLETE":
            return {"status": "complete", "order": last_state}
        if status in FAILED_ORDER_STATUSES:
            return {"status": "failed", "order": last_state}
        time.sleep(poll_interval)
    return {"status": "timeout", "order": last_state}


def get_net_position(kite, symbol):
    positions = kite.positions()
    for p in positions.get("net", []):
        if p.get("tradingsymbol") == symbol:
            return p
    return None


def get_position_pnl(kite, symbol):
    pos = get_net_position(kite, symbol)
    if not pos:
        return None
    try:
        return float(pos.get("pnl"))
    except (TypeError, ValueError):
        return None


def wait_until_position_flat(kite, symbol, timeout=10.0, poll_interval=0.5):
    deadline = time.time() + timeout
    last_pos = None
    while time.time() < deadline:
        last_pos = get_net_position(kite, symbol)
        if not last_pos or int(last_pos.get("quantity", 0)) == 0:
            return True
        time.sleep(poll_interval)
    return False

def place_marketable_limit_exit(kite, exchange, symbol, tx_type, quantity, product, last_price=None, tag=None):
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

        params = {
            "variety": "regular",
            "exchange": exchange,
            "tradingsymbol": symbol,
            "transaction_type": tx_type,
            "quantity": quantity,
            "product": product,
            "order_type": "LIMIT",
            "price": limit_price
        }
        if tag:
            params["tag"] = tag
        return kite.place_order(**params)
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
        if not transaction_type and sl_order_id:
            try:
                order_state = get_latest_order_state(kite, sl_order_id)
                transaction_type = order_state.get("transaction_type") if order_state else None
            except Exception:
                pass
        if not transaction_type:
            return {"status": "error", "message": "Missing transaction_type for SL buffer calculation"}

        rounded_price, limit_price = get_buffered_sl_prices(new_trigger_price, transaction_type)
        
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
            return {"status": "success", "message": f"SL modified to ₹{rounded_price}", "new_sl": rounded_price, "limit_price": limit_price}
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
                price=limit_price,
                tag=f"KQT_SL_{symbol}"[:20]
            )
            print(f"✅ [SL PLACED] {symbol}: New SL at ₹{rounded_price} (limit ₹{limit_price})")
            return {"status": "success", "message": f"New SL placed at ₹{rounded_price}", "new_sl": rounded_price, "limit_price": limit_price, "order_id": order_id}
            
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
                        order_id = place_marketable_limit_exit(kite, exchange, symbol, tx_type, exit_qty, product,
                                                               last_price=p.get("last_price", 0.0), tag=f"KQT_EXIT_{symbol}"[:20])
                        res = wait_for_order_completion(kite, order_id)
                        if res["status"] == "complete" or wait_until_position_flat(kite, symbol, timeout=3.0):
                            summary["squared_positions"] += 1
                        else:
                            summary["errors"].append(f"Square off {symbol} not confirmed: {res['status']}")
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
        exit_order_id = None
        exit_price = None
        realized_pnl = None
        positions = kite.positions()
        net_positions = positions.get("net", [])
        for p in net_positions:
            if p.get("tradingsymbol") == symbol:
                try:
                    realized_pnl = float(p.get("pnl"))
                except (TypeError, ValueError):
                    realized_pnl = None
                qty = p.get("quantity", 0)
                if qty != 0:
                    exchange = p.get("exchange")
                    product = p.get("product")
                    tx_type = "SELL" if qty > 0 else "BUY"
                    exit_qty = abs(qty)
                    
                    exit_order_id = place_marketable_limit_exit(kite, exchange, symbol, tx_type, exit_qty, product,
                                                                last_price=p.get("last_price", 0.0), tag=f"KQT_EXIT_{symbol}"[:20])
                    res = wait_for_order_completion(kite, exit_order_id)
                    order = res.get("order") or {}
                    try:
                        exit_price = float(order.get("average_price") or order.get("price") or 0.0) or None
                    except (TypeError, ValueError):
                        exit_price = None
                    squared = res["status"] == "complete" or wait_until_position_flat(kite, symbol, timeout=3.0)
                    realized_pnl = get_position_pnl(kite, symbol)
                    if not squared:
                        return {"status": "error", "message": f"Exit order {exit_order_id} for {symbol} not confirmed: {res['status']}"}
                    break
        
        return {
            "status": "success" if squared else "error",
            "message": f"Exit completed for {symbol}. Orders cancelled: {cancelled}, Position squared: {squared}",
            "order_id": exit_order_id,
            "exit_price": exit_price,
            "realized_pnl": realized_pnl,
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
        exit_order_id = place_marketable_limit_exit(kite, exchange, symbol, exit_tx_type, half_qty, product,
                                                    last_price=target_pos.get("last_price", 0.0), tag=f"KQT_SCALE_{symbol}"[:20])
        exit_res = wait_for_order_completion(kite, exit_order_id)
        if exit_res["status"] != "complete":
            return {"status": "error", "message": f"Scale-out order {exit_order_id} not confirmed: {exit_res['status']}"}
        
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
                            if otype == "LIMIT":
                                kite.cancel_order(variety=o.get("variety", "regular"), order_id=o.get("order_id"))
                                cancelled_orders += 1
                            elif otype in ["SL", "SL-M"]:
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
