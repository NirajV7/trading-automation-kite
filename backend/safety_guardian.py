"""
Safety Guardian Daemon.
Background safety reconciler that runs every 1 second.
- Evaluates live LTP against virtual targets every 1 second.
- Polls Zerodha positions and orders every 15 seconds to auto-place SLs
  and synchronize target states in active_trades.json.
"""

import os
import json
import time
from datetime import datetime

import config
from kite_auth_manager import check_kite_auth, get_kite_client
from kite_order_manager import modify_or_place_sl, exit_single_position
from kite_utils import round_to_tick
from order_state_machine import close_trade, reconcile_trade, transition_trade
from risk_governor import add_halt_reason, evaluate_rules
from symbol_cooldowns import apply_exit_cooldown
from trade_journal import append_event, record_trade_close
from routers.shared import is_process_running, load_local_trades, save_local_trades, is_logger_enabled


def run_always_on_safety_guardian():
    """
    Background safety reconciler daemon. Runs every 1 second.
    - Evaluates live LTP against virtual targets every 1 second.
    - Polls Zerodha positions and orders every 15 seconds to auto-place SLs
      and synchronize target states in active_trades.json.
    """
    # Import start_logger lazily to avoid circular imports
    from routers.system import start_logger

    print("🛡️ [Safety Guardian] Always-On Safety Guardian daemon started.")
    
    last_broker_poll = 0.0
    active_sls = {}
    
    while True:
        try:
            # Check auth first
            needs_login, _ = check_kite_auth()
            if needs_login:
                add_halt_reason("KITE_AUTH_LOSS", "Kite authentication expired or unavailable.", source="safety_guardian")
            if not needs_login:
                # 1. Self-healing: Ensure logger is running if enabled
                if is_logger_enabled() and not is_process_running("run_data_logger.py"):
                    print("🛡️ [Safety Guardian] Data Logger not running. Auto-recovering logger process...")
                    try:
                        start_logger()
                    except Exception as le:
                        print(f"❌ [Safety Guardian] Failed to auto-recover logger: {le}")
                        
                kite = get_kite_client()
                now = time.time()
                
                # 2. Slow Loop: Poll Zerodha positions and sync active SLs (every 15 seconds)
                if now - last_broker_poll >= 15.0:
                    last_broker_poll = now
                    
                    positions = kite.positions().get("net", [])
                    orders = kite.orders()
                    
                    # Track active open stop-losses on exchange
                    open_statuses = ["OPEN", "TRIGGER PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED"]
                    active_sls = {}
                    for o in orders:
                        if o.get("status") in open_statuses and o.get("order_type") in ["SL", "SL-M"]:
                            active_sls[o["tradingsymbol"]] = {
                                "order_id": o["order_id"],
                                "trigger_price": float(o.get("trigger_price") or o.get("price") or 0.0)
                            }
                            
                    local_trades = load_local_trades()
                    evaluate_rules(positions=positions, active_trades=local_trades, auth_needs_login=False)
                    
                    # Build set of symbols with active positions on Zerodha
                    broker_active_symbols = set()
                    
                    for p in positions:
                        qty = int(p.get("quantity", 0))
                        if qty != 0:
                            symbol = p.get("tradingsymbol")
                            broker_active_symbols.add(symbol)
                            product = p.get("product", "MIS")
                            avg_price = float(p.get("average_price", 0.0))
                            if avg_price <= 0:
                                continue
                                
                            direction = "BUY" if qty > 0 else "SELL"
                            exit_dir = "SELL" if direction == "BUY" else "BUY"

                            # Target orders are virtual now; cancel stale exchange-side target LIMIT orders.
                            for o in orders:
                                if (
                                    o.get("tradingsymbol") == symbol and
                                    o.get("status") in open_statuses and
                                    o.get("transaction_type") == exit_dir and
                                    o.get("order_type") == "LIMIT"
                                ):
                                    try:
                                        kite.cancel_order(variety=o.get("variety", "regular"), order_id=o.get("order_id"))
                                        print(f"🛡️ [Safety Guardian] Cancelled stale target LIMIT order {o.get('order_id')} for {symbol}")
                                    except Exception as cancel_err:
                                        print(f"⚠️ [Safety Guardian] Failed cancelling stale target LIMIT for {symbol}: {cancel_err}")
                            
                            # Case A: Position has no SL on exchange (GHOST SL)
                            if symbol not in active_sls:
                                # Default 1.5% SL distance
                                sl_dist = avg_price * 0.015
                                # Enforce global risk limit from config
                                max_sl_dist = config.RISK_PER_TRADE / abs(qty)
                                if sl_dist > max_sl_dist:
                                    sl_dist = max_sl_dist
                                    
                                sl_price = round_to_tick(avg_price - sl_dist) if direction == "BUY" else round_to_tick(avg_price + sl_dist)
                                
                                print(f"🛡️ [Safety Guardian] Found unprotected position for {symbol} ({qty} shares). Auto-placing SL at ₹{sl_price}...")
                                
                                res = modify_or_place_sl(
                                    symbol=symbol,
                                    new_trigger_price=sl_price,
                                    quantity=abs(qty),
                                    transaction_type=exit_dir,
                                    product=product
                                )
                                print(f"🛡️ [Safety Guardian] Placement result for {symbol}: {res}")
                                sl_id = res.get("order_id") if res.get("status") == "success" else None
                                if sl_id is None:
                                    add_halt_reason("MISSING_SL", f"{symbol} has no confirmed protective SL.", source="safety_guardian")
                            else:
                                # Case B: Position already has an active SL on exchange
                                sl_price = active_sls[symbol]["trigger_price"]
                                sl_id = active_sls[symbol]["order_id"]
                                
                            # Calculate virtual target using 1:2 Risk-Reward ratio
                            sl_width = abs(avg_price - sl_price)
                            target_price = round_to_tick(avg_price + 2.0 * sl_width) if direction == "BUY" else round_to_tick(avg_price - 2.0 * sl_width)
                            
                            # MERGE into local_trades — preserve engine-set values (target, strategy, entry_time)
                            existing_trade = local_trades.get(symbol, {})
                            local_trades[symbol] = {
                                "entry": existing_trade.get("entry", avg_price),
                                "qty": abs(qty),
                                "direction": direction,
                                "sl": sl_price,
                                "target": existing_trade.get("target", target_price),
                                "sl_id": sl_id,
                                "sl_unprotected": sl_id is None,
                                "strategy": existing_trade.get("strategy", "MANUAL"),
                                "entry_time": existing_trade.get("entry_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            }
                            if not existing_trade:
                                reconcile_trade(symbol, direction, abs(qty), avg_price, sl_price, target_price, sl_order_id=sl_id, strategy="MANUAL")
                    
                    # Remove local entries ONLY if confirmed closed on broker (not pending fill)
                    for sym in list(local_trades.keys()):
                        if sym not in broker_active_symbols:
                            # Protect recent entries — order might still be matching on Zerodha
                            entry_time_str = local_trades[sym].get("entry_time", "")
                            try:
                                entry_dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
                                age_seconds = (datetime.now() - entry_dt).total_seconds()
                                if age_seconds > 30:
                                    print(f"🛡️ [Safety Guardian] Removing {sym} — confirmed closed on Zerodha (age: {age_seconds:.0f}s)")
                                    del local_trades[sym]
                                else:
                                    print(f"🛡️ [Safety Guardian] Keeping {sym} (age: {age_seconds:.0f}s) — may be pending fill")
                            except (ValueError, TypeError):
                                # Can't parse entry_time — assume closed
                                print(f"🛡️ [Safety Guardian] Removing {sym} — not on Zerodha, unparseable entry_time")
                                del local_trades[sym]
                    
                    # Save merged result
                    save_local_trades(local_trades)

                # 3. Fast Loop: Evaluate virtual target breaches (every 1 second)
                if os.path.exists(config.LIVE_MARKET_DATA_FILE):
                    try:
                        with open(config.LIVE_MARKET_DATA_FILE, "r") as f:
                            market_snapshot = json.load(f)
                    except Exception:
                        market_snapshot = {}
                        
                    local_trades = load_local_trades()
                    trades_to_exit = []
                    
                    for symbol, trade in local_trades.items():
                        symbol_market = market_snapshot.get(symbol)
                        if not symbol_market:
                            continue
                        ltp = symbol_market.get("ltp")
                        if ltp is None or ltp <= 0:
                            continue
                            
                        direction = trade["direction"]
                        target = trade["target"]
                        
                        target_hit = (direction == "BUY" and ltp >= target) or (direction == "SELL" and ltp <= target)
                        if target_hit:
                            append_event("TARGET_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, reason="Virtual target hit", source="safety_guardian")
                            print(f"🛡️ [Safety Guardian] Virtual Target reached for {symbol} (LTP: ₹{ltp}, Target: ₹{target}). Initiating exit...")
                            trades_to_exit.append(symbol)
                            
                    for symbol in trades_to_exit:
                        try:
                            local_trades = load_local_trades()
                            trade = local_trades.get(symbol, {})
                            transition_trade(symbol, "EXIT_REQUESTED", event_type="EXIT_REQUESTED", reason="Virtual target hit", source="safety_guardian", price=trade.get("target"))
                            # exit_single_position cancels live SL order on Zerodha and squares off position
                            res = exit_single_position(symbol)
                            print(f"🛡️ [Safety Guardian] Exit completed: {res}")
                            
                            # Clean state ONLY if exit succeeded — otherwise keep tracking to retry
                            if res.get("status") == "success":
                                local_trades = load_local_trades()
                                if symbol in local_trades:
                                    trade = local_trades[symbol]
                                    event = record_trade_close(
                                        symbol=symbol,
                                        direction=trade.get("direction"),
                                        entry=float(trade.get("entry", 0.0)),
                                        exit_price=float(trade.get("target", 0.0)),
                                        qty=int(trade.get("qty", 0)),
                                        strategy=trade.get("strategy", ""),
                                        reason="Virtual Target Hit (Safety Guardian)",
                                        source="safety_guardian",
                                    )
                                    apply_exit_cooldown(symbol, trade.get("strategy", ""), "Virtual Target Hit (Safety Guardian)", event.get("pnl", 0.0), source="safety_guardian")
                                    transition_trade(symbol, "EXIT_FILLED", event_type="EXIT_FILLED", reason="Virtual target exit confirmed", source="safety_guardian", price=trade.get("target"))
                                    close_trade(symbol, reason="Virtual target exit confirmed", source="safety_guardian")
                                    del local_trades[symbol]
                                    save_local_trades(local_trades)
                                    print(f"🛡️ [Safety Guardian] Cleaned {symbol} from active_trades.json")
                            else:
                                transition_trade(symbol, "EXIT_FAILED", event_type="EXIT_FAILED", reason=res.get("message"), source="safety_guardian")
                                print(f"⚠️ [Safety Guardian] Exit FAILED for {symbol}, keeping in active_trades for retry. Reason: {res.get('message')}")
                        except Exception as exit_err:
                            transition_trade(symbol, "EXIT_FAILED", event_type="EXIT_FAILED", reason=str(exit_err), source="safety_guardian")
                            print(f"❌ [Safety Guardian] Failed to exit {symbol}: {exit_err}")
                            
        except Exception as e:
            print(f"❌ [Safety Guardian Error] Exception in safety loop: {e}")
            
        time.sleep(1.0)
