"""
Positions Router.
Handles: enriched positions with PnL/SL/Target/ADR, modify SL, modify target.
This is the largest router — contains all position enrichment logic.
"""

import os
import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import config
from kite_telemetry import get_kite_positions, get_kite_orders
from kite_order_manager import modify_or_place_sl
from kite_utils import get_tick_size
from routers.shared import load_local_trades, save_local_trades

router = APIRouter()


@router.get("/api/kite/positions")
def api_positions():
    """
    Fetches open positions from Zerodha and enriches them with:
    - Stop Loss and Target orders linked to the position
    - Real-time ADR (Average Daily Range) exhaustion metrics
    - Total absolute risk (INR) and risk % matching NJ's ₹2,500 guidelines
    """
    positions = get_kite_positions()
    orders = get_kite_orders()
    
    # Load execution core's target/SL state mappings
    engine_active_trades = {}
    if os.path.exists(config.ACTIVE_TRADES_FILE):
        try:
            with open(config.ACTIVE_TRADES_FILE, "r") as f:
                engine_active_trades = json.load(f)
        except Exception:
            pass
            
    # Load live market data file for ADR calculations
    market_snapshot = {}
    if os.path.exists(config.LIVE_MARKET_DATA_FILE):
        try:
            with open(config.LIVE_MARKET_DATA_FILE, "r") as f:
                market_snapshot = json.load(f)
        except Exception as e:
            print(f"❌ [Positions API] Failed to read live market data file: {e}")

    enriched_positions = []
    
    for pos in positions:
        symbol = pos["symbol"]
        qty = pos["quantity"]
        avg_price = pos["average_price"]
        
        # Calculate live PnL based on latest market price if holding active units
        last_price = pos.get("last_price", 0.0)
        # Verify if we have a fresher price in the live websocket logger
        if symbol in market_snapshot:
            ws_price = market_snapshot[symbol].get("ltp")
            if ws_price:
                last_price = ws_price
                
        pnl = pos.get("pnl", 0.0)
        if qty != 0 and last_price > 0:
            pnl = (pos.get("sell_value", 0.0) - pos.get("buy_value", 0.0)) + (qty * last_price)
            
        pnl_pct = 0.0
        if qty != 0 and avg_price > 0:
            pnl_pct = (pnl / (avg_price * abs(qty))) * 100.0
            
        # 1. Match active orders to link bracket stops (Target Limit and Trigger SL)
        target_price = None
        target_order_id = None
        target_status = None
        
        sl_price = None
        sl_order_id = None
        sl_status = None
        sl_order_type = None
        
        expected_tx = "SELL" if qty > 0 else "BUY"
        open_statuses = ["OPEN", "TRIGGER PENDING"]
        
        for o in orders:
            if o.get("symbol") == symbol and o.get("status") in open_statuses:
                if o.get("transaction_type") == expected_tx:
                    otype = o.get("order_type")
                    if otype == "LIMIT":
                        target_price = o.get("price")
                        target_order_id = o.get("order_id")
                        target_status = o.get("status")
                    elif otype in ["SL", "SL-M"]:
                        sl_price = o.get("trigger_price") or o.get("price")
                        sl_order_id = o.get("order_id")
                        sl_status = o.get("status")
                        sl_order_type = otype
                        
        # 2. Get local engine properties
        trade_details = engine_active_trades.get(symbol, {})
        engine_target = trade_details.get("target")
        engine_sl = trade_details.get("sl")
        strategy = trade_details.get("strategy", "UNTRACKED")
        entry_time = trade_details.get("entry_time", None)

        # 3. ADR Metrics
        adr_val = 0.0
        adr_abs_val = 0.0
        today_open = None
        today_high = None
        today_low = None
        
        symbol_market = market_snapshot.get(symbol, {})
        if symbol_market:
            adr_val = symbol_market.get("adr_percentage", 0.0)
            adr_abs_val = symbol_market.get("adr_absolute", 0.0)
            # Use current LTP to calculate range boundaries
            today_high = last_price
            today_low = last_price
            
        # Calculate dynamic range expansion
        today_range = 0.0
        adr_exhaustion_pct = 0.0
        if adr_abs_val and adr_abs_val > 0 and last_price > 0:
            # Look at daily high/low boundaries if we have them
            if qty > 0: # Long
                # Exhaustion based on progress toward target
                today_range = max(0.0, last_price - avg_price)
            else: # Short
                today_range = max(0.0, avg_price - last_price)
            adr_exhaustion_pct = (today_range / adr_abs_val) * 100.0

        # 4. Risk Assessments (₹2500 max limit)
        allocated_risk = 0.0
        risk_pct = 0.0
        
        effective_sl = sl_price or engine_sl
        if qty != 0:
            if effective_sl:
                allocated_risk = abs(qty * (avg_price - effective_sl))
                risk_pct = min(100.0, (allocated_risk / config.RISK_PER_TRADE) * 100.0)
            elif adr_abs_val:
                # Mock risk if no stop placed
                allocated_risk = abs(qty * adr_abs_val)
                risk_pct = min(100.0, (allocated_risk / config.RISK_PER_TRADE) * 100.0)

        # 5. Risk-Reward Ratio (R:R)
        rr_ratio = 0.0
        effective_target = target_price or engine_target
        if qty != 0 and effective_sl and effective_target:
            reward_dist = abs(effective_target - avg_price)
            risk_dist = abs(avg_price - effective_sl)
            if risk_dist > 0:
                rr_ratio = reward_dist / risk_dist

        # 6. Distance to targets in % and Rs
        dist_to_target_pct = None
        dist_to_sl_pct = None
        target_dist_rs = None
        sl_dist_rs = None
        
        if qty != 0 and last_price > 0:
            if qty > 0: # Long
                if effective_target:
                    target_dist_rs = effective_target - last_price
                    dist_to_target_pct = (target_dist_rs / last_price) * 100.0
                if effective_sl:
                    sl_dist_rs = last_price - effective_sl
                    dist_to_sl_pct = (sl_dist_rs / last_price) * 100.0
            else: # Short
                if effective_target:
                    target_dist_rs = last_price - effective_target
                    dist_to_target_pct = (target_dist_rs / last_price) * 100.0
                if effective_sl:
                    sl_dist_rs = effective_sl - last_price
                    dist_to_sl_pct = (sl_dist_rs / last_price) * 100.0

        enriched_positions.append({
            "symbol": symbol,
            "quantity": qty,
            "average_price": round(avg_price, 2),
            "last_price": round(last_price, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "product": pos.get("product"),
            "strategy": strategy,
            "entry_time": entry_time,
            "tick_size": get_tick_size(last_price or avg_price),
            
            # Stop loss & Limit brackets
            "target_price": target_price,
            "target_order_id": target_order_id,
            "target_status": target_status,
            "sl_price": sl_price,
            "sl_order_id": sl_order_id,
            "sl_status": sl_status,
            "sl_order_type": sl_order_type,
            "engine_target": effective_target,
            "engine_sl": effective_sl,
            
            # Risk & Stats
            "adr": round(adr_val, 2),
            "adr_abs": round(adr_abs_val, 2),
            "adr_exhaustion_pct": round(adr_exhaustion_pct, 2),
            "allocated_risk": round(allocated_risk, 2),
            "risk_pct": round(risk_pct, 1),
            "rr_ratio": round(rr_ratio, 2),
            
            # Distance Metrics
            "dist_to_target_pct": round(dist_to_target_pct, 2) if dist_to_target_pct is not None else None,
            "dist_to_sl_pct": round(dist_to_sl_pct, 2) if dist_to_sl_pct is not None else None,
            "target_dist_rs": round(target_dist_rs, 2) if target_dist_rs is not None else None,
            "sl_dist_rs": round(sl_dist_rs, 2) if sl_dist_rs is not None else None
        })
        
    return JSONResponse({"positions": enriched_positions})


@router.post("/api/kite/modify_sl")
async def execute_modify_sl(request: Request):
    """
    Modifies an active position's Stop Loss trigger and limit orders.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol")
        new_sl = data.get("new_sl_price")
        sl_order_id = data.get("sl_order_id")
        quantity = data.get("quantity")
        transaction_type = data.get("transaction_type")
        product = data.get("product")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not symbol or new_sl is None:
        return JSONResponse({"status": "error", "message": "symbol and new_sl_price are required"}, status_code=400)
        
    res = modify_or_place_sl(
        symbol=symbol,
        new_trigger_price=float(new_sl),
        sl_order_id=sl_order_id,
        quantity=quantity,
        transaction_type=transaction_type,
        product=product
    )
    if res.get("status") == "error":
        return JSONResponse(res, status_code=500)
        
    # Immediately sync the new SL to active_trades.json if tracked
    if res.get("status") == "success":
        new_sl_val = res.get("new_sl") or float(new_sl)
        if os.path.exists(config.ACTIVE_TRADES_FILE):
            try:
                with open(config.ACTIVE_TRADES_FILE, "r") as f:
                    local_trades = json.load(f)
                if symbol in local_trades:
                    local_trades[symbol]["sl"] = new_sl_val
                    if res.get("order_id"):
                        local_trades[symbol]["sl_id"] = res.get("order_id")
                    elif sl_order_id:
                        local_trades[symbol]["sl_id"] = sl_order_id
                    
                    temp_path = f"{config.ACTIVE_TRADES_FILE}.tmp"
                    with open(temp_path, "w") as f:
                        json.dump(local_trades, f, indent=4)
                    os.replace(temp_path, config.ACTIVE_TRADES_FILE)
                    print(f"🛡️ [API modify_sl] Immediately updated sl to ₹{new_sl_val} in active_trades.json")
            except Exception as e:
                print(f"❌ [API modify_sl] Failed to immediately update active_trades.json: {e}")
                
    return JSONResponse(res)


@router.post("/api/kite/modify_target")
async def execute_modify_target(request: Request):
    """
    Modifies an active position's target price.
    If it's on Zerodha (open limit order), modify the order.
    Also update/persist it in active_trades.json.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol")
        new_target = data.get("new_target_price")
        target_order_id = data.get("target_order_id")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not symbol or new_target is None:
        return JSONResponse({"status": "error", "message": "symbol and new_target_price are required"}, status_code=400)
        
    from kite_utils import round_to_tick
    rounded_target = round_to_tick(float(new_target))
    
    # 1. Update active_trades.json if the trade is in there
    updated_local = False
    if os.path.exists(config.ACTIVE_TRADES_FILE):
        try:
            with open(config.ACTIVE_TRADES_FILE, "r") as f:
                local_trades = json.load(f)
            if symbol in local_trades:
                local_trades[symbol]["target"] = rounded_target
                temp_path = f"{config.ACTIVE_TRADES_FILE}.tmp"
                with open(temp_path, "w") as f:
                    json.dump(local_trades, f, indent=4)
                os.replace(temp_path, config.ACTIVE_TRADES_FILE)
                print(f"✅ [API modify_target] Immediately updated target to ₹{rounded_target} in active_trades.json")
                updated_local = True
        except Exception as e:
            print(f"❌ [API modify_target] Failed to write to active_trades: {e}")
            
    # 2. Modify Zerodha limit order if target_order_id was passed or can be found
    kite = None
    try:
        from kite_auth_manager import check_kite_auth, get_kite_client
        needs_login, _ = check_kite_auth()
        if not needs_login:
            kite = get_kite_client()
    except Exception:
        pass
        
    if kite:
        try:
            if not target_order_id:
                orders = kite.orders()
                open_statuses = ["OPEN", "TRIGGER PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED"]
                for o in orders:
                    if o.get("tradingsymbol") == symbol and o.get("status") in open_statuses:
                        if o.get("order_type") == "LIMIT":
                            target_order_id = o.get("order_id")
                            break
                            
            if target_order_id:
                kite.modify_order(
                    variety="regular",
                    order_id=target_order_id,
                    order_type="LIMIT",
                    price=rounded_target
                )
                print(f"✅ [Target ZERODHA MODIFY] {symbol}: Target order modified to ₹{rounded_target}")
                return JSONResponse({"status": "success", "message": f"Target modified on Zerodha to ₹{rounded_target}", "new_target": rounded_target})
        except Exception as e:
            print(f"⚠️ [Target ZERODHA MODIFY ERROR] {symbol}: {e}")
            return JSONResponse({
                "status": "partial", 
                "message": f"Updated locally to ₹{rounded_target}, but Zerodha order modification failed: {str(e)}", 
                "new_target": rounded_target
            })
            
    if updated_local:
        return JSONResponse({"status": "success", "message": f"Virtual target updated locally to ₹{rounded_target}", "new_target": rounded_target})
        
    return JSONResponse({"status": "error", "message": f"Position {symbol} not tracked locally or on Zerodha"}, status_code=400)
