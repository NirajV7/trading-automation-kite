"""
Orders Router.
Handles: fetching orders, cancelling orders, modifying orders, panic exit, single position exit, scale out.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kite_telemetry import get_kite_orders, get_kite_positions
from kite_order_manager import panic_square_off, exit_single_position, book_half_position
from trade_journal import append_event

router = APIRouter()


@router.get("/api/kite/orders")
def api_orders():
    """
    Returns active & historical Zerodha orders.
    """
    return JSONResponse({"orders": get_kite_orders()})


@router.post("/api/kite/orders/cancel")
async def cancel_order(request: Request):
    """
    Cancels a pending order on Zerodha Kite.
    """
    try:
        data = await request.json()
        order_id = data.get("order_id")
        variety = data.get("variety", "regular")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not order_id:
        return JSONResponse({"status": "error", "message": "order_id is required"}, status_code=400)
        
    try:
        from kite_auth_manager import get_kite_client
        kite = get_kite_client()
        res = kite.cancel_order(variety=variety, order_id=order_id)
        return JSONResponse({"status": "success", "message": f"Order {order_id} cancelled successfully", "order_id": res})
    except Exception as e:
        print(f"[API ERROR] Failed to cancel order {order_id}: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/kite/orders/modify")
async def modify_order(request: Request):
    """
    Modifies a pending order on Zerodha Kite.
    """
    try:
        data = await request.json()
        order_id = data.get("order_id")
        variety = data.get("variety", "regular")
        quantity = int(data.get("quantity"))
        price = float(data.get("price"))
        trigger_price = float(data.get("trigger_price", 0.0))
        order_type = data.get("order_type")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload or value types"}, status_code=400)
        
    if not order_id or not order_type:
        return JSONResponse({"status": "error", "message": "order_id and order_type are required"}, status_code=400)
        
    try:
        from kite_auth_manager import get_kite_client
        kite = get_kite_client()
        
        # Prepare modification parameters
        params = {
            "variety": variety,
            "order_id": order_id,
            "quantity": quantity,
            "order_type": order_type
        }
        # Only pass price / trigger_price if relevant for the order type
        if order_type in ["LIMIT", "SL"]:
            params["price"] = price
        if order_type in ["SL", "SL-M"]:
            params["trigger_price"] = trigger_price
            
        res = kite.modify_order(**params)
        return JSONResponse({"status": "success", "message": f"Order {order_id} modified successfully", "order_id": res})
    except Exception as e:
        print(f"[API ERROR] Failed to modify order {order_id}: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/kite/panic")
def execute_panic():
    """
    Emergency panic kill switch. Cancels all pending orders and squares off
    all active net positions immediately using marketable limit orders.
    """
    res = panic_square_off()
    append_event("PANIC_EXIT", state="EXIT_REQUESTED", reason=res.get("message"), source="ui")
    # Force cache refresh in telemetry
    get_kite_positions(force=True)
    if res.get("status") == "error":
        return JSONResponse(res, status_code=500)
    return JSONResponse(res)


@router.post("/api/kite/exit_position")
async def execute_exit_position(request: Request):
    """
    Closes a single active position and cancels its pending stop/target brackets.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not symbol:
        return JSONResponse({"status": "error", "message": "Symbol is required"}, status_code=400)
        
    res = exit_single_position(symbol)
    append_event("MANUAL_EXIT", symbol=symbol, state="EXIT_REQUESTED", reason=res.get("message"), source="ui")
    get_kite_positions(force=True)
    if res.get("status") == "error":
        return JSONResponse(res, status_code=500)
    return JSONResponse(res)


@router.post("/api/kite/scale_out")
async def execute_scale_out(request: Request):
    """
    Reduces the position size by 50% to lock in partial profits.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not symbol:
        return JSONResponse({"status": "error", "message": "Symbol is required"}, status_code=400)
        
    res = book_half_position(symbol)
    append_event("SCALE_OUT", symbol=symbol, state="ACTIVE", reason=res.get("message"), source="ui")
    get_kite_positions(force=True)
    if res.get("status") == "error":
        return JSONResponse(res, status_code=500)
    return JSONResponse(res)
