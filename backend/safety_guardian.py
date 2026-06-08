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
from market_data_guard import confirm_exit_trigger
from temporary_trade_controls import (
    TEMPORARY_PROFIT_REASON,
    calculate_temporary_sl_price,
    calculate_trade_pnl,
    confirm_temporary_profit_exit,
    temporary_profit_booking_enabled,
    temporary_profit_threshold,
    temporary_sl_cap_enabled,
)
from kite_utils import round_to_tick
from order_state_machine import begin_exit, close_trade, finish_exit, get_trade_state, reconcile_trade, transition_trade, release_exit_lock
from risk_governor import add_halt_reason, evaluate_rules
from symbol_cooldowns import apply_exit_cooldown
from trade_journal import append_event, record_trade_close
from routers.shared import is_process_running, load_local_trades, is_logger_enabled
from active_trade_store import ActiveTradeStoreError, merge_trades, remove_trade


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

                    broker_active_symbols = set()
                    broker_updates = {}

                    for p in positions:
                        qty = int(p.get("quantity", 0))
                        if qty == 0:
                            continue
                        symbol = p.get("tradingsymbol")
                        broker_active_symbols.add(symbol)
                        product = p.get("product", "MIS")
                        avg_price = float(p.get("average_price", 0.0))
                        if avg_price <= 0:
                            continue

                        direction = "BUY" if qty > 0 else "SELL"
                        exit_dir = "SELL" if direction == "BUY" else "BUY"

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

                        if symbol not in active_sls:
                            sl_price = None
                            if temporary_sl_cap_enabled():
                                sl_price = calculate_temporary_sl_price(avg_price, abs(qty), direction)
                                if sl_price is not None:
                                    print(f"🛡️ [Safety Guardian] Temporary SL cap active for {symbol}. Auto-placing ₹500-risk SL at ₹{sl_price}...")

                            if sl_price is None:
                                sl_dist = avg_price * 0.015
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
                            sl_price = active_sls[symbol]["trigger_price"]
                            sl_id = active_sls[symbol]["order_id"]

                        sl_width = abs(avg_price - sl_price)
                        target_price = round_to_tick(avg_price + 2.0 * sl_width) if direction == "BUY" else round_to_tick(avg_price - 2.0 * sl_width)
                        broker_updates[symbol] = {
                            "avg_price": avg_price,
                            "qty": abs(qty),
                            "direction": direction,
                            "sl": sl_price,
                            "target": target_price,
                            "sl_id": sl_id,
                            "sl_unprotected": sl_id is None,
                        }

                    def apply_broker_snapshot(latest_trades):
                        for symbol, update in broker_updates.items():
                            existing_trade = latest_trades.get(symbol, {})
                            latest_trades[symbol] = {
                                "entry": existing_trade.get("entry", update["avg_price"]),
                                "qty": update["qty"],
                                "direction": update["direction"],
                                "sl": update["sl"],
                                "target": existing_trade.get("target", update["target"]),
                                "entry_id": existing_trade.get("entry_id"),
                                "target_id": existing_trade.get("target_id"),
                                "sl_id": update["sl_id"],
                                "sl_unprotected": update["sl_unprotected"],
                                "strategy": existing_trade.get("strategy", "MANUAL"),
                                "entry_time": existing_trade.get("entry_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            }
                            if not existing_trade:
                                reconcile_trade(symbol, update["direction"], update["qty"], update["avg_price"], update["sl"], update["target"], sl_order_id=update["sl_id"], strategy="MANUAL")

                        for sym in list(latest_trades.keys()):
                            if sym in broker_active_symbols:
                                continue
                            entry_time_str = latest_trades[sym].get("entry_time", "")
                            try:
                                entry_dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
                                age_seconds = (datetime.now() - entry_dt).total_seconds()
                                if age_seconds <= 30:
                                    print(f"🛡️ [Safety Guardian] Keeping {sym} (age: {age_seconds:.0f}s) — may be pending fill")
                                    continue
                                print(f"🛡️ [Safety Guardian] Removing {sym} — confirmed closed on Zerodha (age: {age_seconds:.0f}s)")
                                trade = latest_trades[sym]
                                broker_pos = next((p for p in positions if p.get("tradingsymbol") == sym), {})
                                realized_pnl = None
                                try:
                                    realized_pnl = float(broker_pos.get("pnl"))
                                except (TypeError, ValueError):
                                    realized_pnl = None
                                entry = float(trade.get("entry", 0.0) or 0.0)
                                qty = int(trade.get("qty", 0) or 0)
                                direction = trade.get("direction")
                                exit_price = entry
                                if realized_pnl is not None and entry > 0 and qty > 0:
                                    exit_price = entry + (realized_pnl / qty) if direction == "BUY" else entry - (realized_pnl / qty)
                                elif broker_pos.get("last_price"):
                                    exit_price = float(broker_pos.get("last_price"))

                                sl_id = trade.get("sl_id")
                                sl_completed = any(o.get("order_id") == sl_id and o.get("status") == "COMPLETE" for o in orders)
                                reason = "Stop Loss Hit (broker SL complete)" if sl_completed else "Manual Closed (Kite)"
                                if sl_id and not sl_completed:
                                    for o in orders:
                                        if o.get("order_id") == sl_id and o.get("status") in open_statuses:
                                            try:
                                                kite.cancel_order(variety=o.get("variety", "regular"), order_id=sl_id)
                                                print(f"🛡️ [Safety Guardian] Cancelled orphan SL order {sl_id} for {sym}")
                                            except Exception as cancel_err:
                                                print(f"⚠️ [Safety Guardian] Failed cancelling orphan SL {sl_id} for {sym}: {cancel_err}")
                                            break
                                state = get_trade_state(sym) or {}
                                if state.get("state") == "CLOSED":
                                    close_reason = state.get("last_reason") or state.get("reason") or "already closed"
                                    print(f"🛡️ [Safety Guardian] Skipping duplicate close for {sym}; state already CLOSED ({close_reason})")
                                    del latest_trades[sym]
                                    continue
                                if sl_completed:
                                    append_event("SL_HIT", symbol=sym, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=qty, price=exit_price, order_id=sl_id, reason="Broker SL order complete", source="safety_guardian")
                                event = record_trade_close(
                                    symbol=sym,
                                    direction=direction,
                                    entry=entry,
                                    exit_price=exit_price,
                                    qty=qty,
                                    strategy=trade.get("strategy", ""),
                                    reason=reason,
                                    source="safety_guardian",
                                    realized_pnl=realized_pnl,
                                    order_id=sl_id if sl_completed else None,
                                    pnl_pending=realized_pnl is None,
                                )
                                apply_exit_cooldown(sym, trade.get("strategy", ""), reason, event.get("pnl", 0.0), source="safety_guardian")
                                transition_trade(sym, "EXIT_REQUESTED", event_type="EXIT_REQUESTED", reason=reason, source="safety_guardian", price=exit_price)
                                transition_trade(sym, "EXIT_FILLED", event_type="EXIT_FILLED", reason=reason, source="safety_guardian", price=exit_price, order_id=sl_id if sl_completed else None)
                                close_trade(sym, reason=reason, source="safety_guardian")
                                del latest_trades[sym]
                            except (ValueError, TypeError):
                                print(f"🛡️ [Safety Guardian] Removing {sym} — not on Zerodha, unparseable entry_time")
                                del latest_trades[sym]
                        return dict(latest_trades)

                    try:
                        local_trades = merge_trades(apply_broker_snapshot, source="safety_guardian")
                    except ActiveTradeStoreError as store_err:
                        print(f"⚠️ [Safety Guardian] Skipping active_trades save cycle: {store_err}")
                        local_trades = load_local_trades()

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

                        profit_pnl = calculate_trade_pnl(trade.get("entry"), ltp, trade.get("qty"), direction)
                        if temporary_profit_booking_enabled() and profit_pnl >= temporary_profit_threshold():
                            confirm = confirm_temporary_profit_exit(symbol, trade, ltp)
                            if not confirm.get("confirmed"):
                                msg = f"Exit skipped: stale cache not confirmed for {symbol} temporary profit (cached ₹{ltp}, fresh {confirm.get('ltp')}, pnl {confirm.get('pnl')}, reason: {confirm.get('reason')})"
                                append_event("EXIT_SKIPPED", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, pnl=profit_pnl, reason=msg, source="safety_guardian")
                                print(f"🛡️ [Safety Guardian] {msg}")
                                continue
                            confirmed_ltp = confirm.get("ltp") or ltp
                            confirmed_pnl = confirm.get("pnl") if confirm.get("pnl") is not None else profit_pnl
                            append_event("PROFIT_BOOKING_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=confirmed_ltp, pnl=confirmed_pnl, reason=TEMPORARY_PROFIT_REASON, source="safety_guardian")
                            print(f"🛡️ [Safety Guardian] Temporary profit booking reached for {symbol} (PnL: ₹{confirmed_pnl:.2f}, LTP: ₹{confirmed_ltp}). Initiating exit...")
                            trades_to_exit.append({"symbol": symbol, "price": confirmed_ltp, "reason": TEMPORARY_PROFIT_REASON, "close_reason": f"{TEMPORARY_PROFIT_REASON} (Safety Guardian)", "state_reason": "Temporary profit booking exit confirmed"})
                            continue

                        target_hit = (direction == "BUY" and ltp >= target) or (direction == "SELL" and ltp <= target)
                        if target_hit:
                            confirm = confirm_exit_trigger(symbol, direction, target, "target", ltp)
                            if not confirm.get("confirmed"):
                                msg = f"Exit skipped: stale cache not confirmed for {symbol} target (cached ₹{ltp}, fresh {confirm.get('ltp')}, reason: {confirm.get('reason')})"
                                append_event("EXIT_SKIPPED", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, reason=msg, source="safety_guardian")
                                print(f"🛡️ [Safety Guardian] {msg}")
                                continue
                            confirmed_ltp = confirm.get("ltp") or ltp
                            append_event("TARGET_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=confirmed_ltp, reason="Virtual target hit", source="safety_guardian")
                            print(f"🛡️ [Safety Guardian] Virtual Target reached for {symbol} (LTP: ₹{confirmed_ltp}, Target: ₹{target}). Initiating exit...")
                            trades_to_exit.append({"symbol": symbol, "price": confirmed_ltp, "reason": "Virtual target hit", "close_reason": "Virtual Target Hit (Safety Guardian)", "state_reason": "Virtual target exit confirmed"})
                            
                    for exit_item in trades_to_exit:
                        symbol = exit_item["symbol"] if isinstance(exit_item, dict) else exit_item
                        exit_price_hint = exit_item.get("price") if isinstance(exit_item, dict) else None
                        exit_reason = exit_item.get("reason") if isinstance(exit_item, dict) else "Virtual target hit"
                        close_reason = exit_item.get("close_reason") if isinstance(exit_item, dict) else "Virtual Target Hit (Safety Guardian)"
                        state_reason = exit_item.get("state_reason") if isinstance(exit_item, dict) else "Virtual target exit confirmed"
                        try:
                            local_trades = load_local_trades()
                            trade = local_trades.get(symbol, {})
                            gate = begin_exit(symbol, exit_reason, "safety_guardian", price=exit_price_hint or trade.get("target"))
                            if not gate.get("ok"):
                                print(f"🛡️ [Safety Guardian] Exit already in progress for {symbol}: {gate.get('message')}")
                                continue
                            local_trades = load_local_trades()
                            if symbol not in local_trades:
                                release_exit_lock(symbol)
                                continue
                            trade = local_trades[symbol]
                            try:
                                # exit_single_position cancels live SL order on Zerodha and squares off position
                                res = exit_single_position(symbol)
                                print(f"🛡️ [Safety Guardian] Exit completed: {res}")
                            except Exception:
                                release_exit_lock(symbol)
                                raise
                            
                            # Clean state ONLY if exit succeeded — otherwise keep tracking to retry
                            if res.get("status") == "success":
                                local_trades = load_local_trades()
                                if symbol in local_trades:
                                    trade = local_trades[symbol]
                                    event = record_trade_close(
                                        symbol=symbol,
                                        direction=trade.get("direction"),
                                        entry=float(trade.get("entry", 0.0)),
                                        exit_price=float(res.get("exit_price") or trade.get("target", 0.0)),
                                        qty=int(trade.get("qty", 0)),
                                        strategy=trade.get("strategy", ""),
                                        reason=close_reason,
                                        source="safety_guardian",
                                        realized_pnl=res.get("realized_pnl"),
                                        order_id=res.get("order_id"),
                                        pnl_pending=res.get("realized_pnl") is None,
                                    )
                                    apply_exit_cooldown(symbol, trade.get("strategy", ""), close_reason, event.get("pnl", 0.0), source="safety_guardian")
                                    finish_exit(symbol, True, state_reason, "safety_guardian", price=res.get("exit_price") or exit_price_hint or trade.get("target"), order_id=res.get("order_id"))
                                    close_trade(symbol, reason=state_reason, source="safety_guardian")
                                    try:
                                        remove_trade(symbol, source="safety_guardian")
                                    except ActiveTradeStoreError as store_err:
                                        print(f"⚠️ [Safety Guardian] Failed removing {symbol} from active_trades.json: {store_err}")
                                    del local_trades[symbol]
                                    print(f"🛡️ [Safety Guardian] Cleaned {symbol} from active_trades.json")
                                else:
                                    release_exit_lock(symbol)
                            else:
                                finish_exit(symbol, False, res.get("message"), "safety_guardian")
                                print(f"⚠️ [Safety Guardian] Exit FAILED for {symbol}, keeping in active_trades for retry. Reason: {res.get('message')}")
                        except Exception as exit_err:
                            finish_exit(symbol, False, str(exit_err), "safety_guardian")
                            print(f"❌ [Safety Guardian] Failed to exit {symbol}: {exit_err}")
                            
        except Exception as e:
            print(f"❌ [Safety Guardian Error] Exception in safety loop: {e}")
            
        time.sleep(1.0)
