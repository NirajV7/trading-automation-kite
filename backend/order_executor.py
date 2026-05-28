import time
from datetime import datetime
from config import RISK_PER_TRADE, CAPITAL_ALLOCATION
from kite_auth_manager import get_kite_client
from kite_utils import round_to_tick, handle_auth_failure
from kite_order_manager import modify_or_place_sl, wait_for_order_completion
from order_state_machine import get_trade_state, has_open_trade, start_trade, transition_trade, close_trade
from risk_governor import add_halt_reason, can_open_trade
from symbol_cooldowns import apply_exit_cooldown, entry_error_cooldown
from trade_journal import append_event, record_trade_close

class OrderExecutorMixin:
    def calculate_position_size(self, symbol, entry_price, sl_price):
        """
        Calculates position quantity dynamically based on risk constraints.
        Formula: Quantity = RISK_PER_TRADE (₹2,500) / (Entry - SL)
        Ensures position value doesn't exceed 1/3 of total capital (₹1.66 Lakh).
        """
        try:
            sl_width = abs(entry_price - sl_price)
            if sl_width <= 0:
                self.log_message(f"Invalid SL width for {symbol} (SL price = {sl_price}). Sizing aborted.", is_error=True)
                return 0
                
            # Quantity based on risk tolerance (₹2500 per trade)
            raw_qty = int(RISK_PER_TRADE / sl_width)
            
            # Apply maximum capital cap to protect margin (1/3 of ₹5 Lakh = ₹1.66 Lakh)
            max_capital_per_trade = CAPITAL_ALLOCATION / 3.0
            max_qty_cap = int(max_capital_per_trade / entry_price)
            
            final_qty = min(raw_qty, max_qty_cap)
            self.log_message(f"Sizing {symbol}: Raw Qty={raw_qty}, Cap Qty={max_qty_cap} (using final quantity {final_qty})")
            return max(0, final_qty)
        except Exception as e:
            self.log_message(f"Error sizing position for {symbol}: {e}", is_error=True)
            return 0

    def trigger_mock_order_placement(self, symbol, direction, qty, price, sl, target, strategy):
        """Simulates placing and filling bracket orders instantly for dry-run trading."""
        if has_open_trade(symbol):
            append_event("SIGNAL_BLOCKED", symbol=symbol, strategy=strategy, direction=direction, state="BLOCKED", qty=qty, price=price, reason="Duplicate open state", source="dry_run")
            self.log_message(f"[DRY-RUN] State machine blocked duplicate entry for {symbol}", is_error=True)
            return

        started = start_trade(symbol, strategy, direction, qty=qty, price=price, sl=sl, target=target, source="dry_run")
        if not started.get("ok"):
            append_event("SIGNAL_BLOCKED", symbol=symbol, strategy=strategy, direction=direction, state="BLOCKED", qty=qty, price=price, reason=started.get("message"), source="dry_run")
            self.log_message(f"[DRY-RUN] State machine blocked {symbol}: {started.get('message')}", is_error=True)
            return
        transition_trade(symbol, "PRECHECK_PASSED", event_type="PRECHECK_PASSED", reason="Dry-run precheck passed", source="dry_run")

        governor_gate = can_open_trade(symbol, strategy, active_trades=self.active_trades)
        if not governor_gate.get("allowed"):
            transition_trade(symbol, "BLOCKED", event_type="SIGNAL_BLOCKED", reason=governor_gate.get("message"), source="risk_governor")
            self.log_message(f"[DRY-RUN] Risk Governor blocked {strategy} entry for {symbol}: {governor_gate.get('message')}", is_error=True)
            return

        order_id = f"MOCK_ENTRY_{int(time.time())}"
        sl_id = f"MOCK_SL_{int(time.time())}"
        transition_trade(symbol, "ENTRY_SENT", event_type="ENTRY_SENT", reason="Mock entry sent", source="dry_run", entry_order_id=order_id, order_id=order_id, price=price)
        transition_trade(symbol, "ENTRY_FILLED", event_type="ENTRY_FILLED", reason="Mock entry filled", source="dry_run", entry_order_id=order_id, order_id=order_id, price=price)
        transition_trade(symbol, "SL_PLACED", event_type="SL_PLACED", reason="Mock SL placed", source="dry_run", sl_order_id=sl_id, order_id=sl_id, price=sl)
        transition_trade(symbol, "ACTIVE", event_type="TRADE_ACTIVE", reason="Mock trade active", source="dry_run")
        
        with self.lock:
            self.active_trades[symbol] = {
                "entry": price,
                "qty": qty,
                "direction": direction,
                "sl": sl,
                "target": target,
                "entry_id": order_id,
                "sl_id": sl_id,
                "target_id": None,
                "sl_unprotected": False,
                "strategy": strategy,
                "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.save_active_trades()
            
        self.log_message(f"[DRY-RUN] Filled mock {direction} for {symbol}. Qty: {qty} @ ₹{price}, SL: ₹{sl}, Target: ₹{target}")

    def execute_live_order_placement(self, symbol, direction, qty, price, sl, target, strategy):
        """Submits real entry orders and bracket safety orders to Zerodha Kite."""
        order_id = None
        try:
            if has_open_trade(symbol):
                append_event("SIGNAL_BLOCKED", symbol=symbol, strategy=strategy, direction=direction, state="BLOCKED", qty=qty, price=price, reason="Duplicate open state", source="execution")
                self.log_message(f"State machine blocked duplicate live entry for {symbol}", is_error=True)
                return

            started = start_trade(symbol, strategy, direction, qty=qty, price=price, sl=sl, target=target, source="execution")
            if not started.get("ok"):
                append_event("SIGNAL_BLOCKED", symbol=symbol, strategy=strategy, direction=direction, state="BLOCKED", qty=qty, price=price, reason=started.get("message"), source="execution")
                self.log_message(f"State machine blocked live entry for {symbol}: {started.get('message')}", is_error=True)
                return
            transition_trade(symbol, "PRECHECK_PASSED", event_type="PRECHECK_PASSED", reason="Execution precheck passed", source="execution")

            governor_gate = can_open_trade(symbol, strategy, active_trades=self.active_trades)
            if not governor_gate.get("allowed"):
                transition_trade(symbol, "BLOCKED", event_type="SIGNAL_BLOCKED", reason=governor_gate.get("message"), source="risk_governor")
                self.log_message(f"Risk Governor blocked live {strategy} entry for {symbol}: {governor_gate.get('message')}", is_error=True)
                return

            self.kite = get_kite_client()
            
            # Place entry market order (MIS product for intraday execution leverage)
            tag = f"KQT_{strategy}_{symbol}"[:20]
            self.log_message(f"Submitting live entry order: {direction} {qty} {symbol} MIS...")
            order_id = self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=symbol,
                transaction_type=direction,
                quantity=qty,
                product="MIS",
                order_type="MARKET",
                market_protection=-1,
                tag=tag
            )
            transition_trade(symbol, "ENTRY_SENT", event_type="ENTRY_SENT", reason="Live entry order submitted", source="execution", entry_order_id=order_id, order_id=order_id, price=price)
            
            # Confirm fill before creating local trade state.
            fill_result = wait_for_order_completion(self.kite, order_id, timeout=10.0)
            if fill_result["status"] != "complete":
                state = fill_result.get("order") or {}
                failed_state = "ENTRY_REJECTED" if fill_result["status"] == "failed" else "ENTRY_TIMEOUT"
                transition_trade(symbol, failed_state, event_type=failed_state, reason=f"Entry order {order_id} not filled: {state.get('status', fill_result['status'])}", source="execution", order_id=order_id)
                entry_error_cooldown(symbol, strategy, failed_state, source="execution")
                self.log_message(f"Entry order {order_id} not completely filled: {state.get('status', fill_result['status'])}", is_error=True)
                return

            entry_order = fill_result["order"]
            if not entry_order.get("average_price"):
                for order in self.kite.orders():
                    if order.get("order_id") == order_id:
                        entry_order = order
                        break
            fill_price = float(entry_order.get("average_price") or price)
            filled_qty = int(entry_order.get("filled_quantity") or entry_order.get("quantity") or qty)
            if filled_qty <= 0:
                raise RuntimeError(f"Entry order {order_id} completed but filled quantity is zero")
            transition_trade(symbol, "ENTRY_FILLED", event_type="ENTRY_FILLED", reason="Live entry filled", source="execution", qty=filled_qty, entry_price=fill_price, price=fill_price, order_id=order_id)
            
            # Calculate exit direction for brackets
            exit_dir = "SELL" if direction == "BUY" else "BUY"
            
            # Place protective stop-loss SL order. Target remains virtual in active_trades.
            self.log_message(f"Submitting stop-loss trigger order: {exit_dir} {qty} {symbol} trigger ₹{sl}...")
            sl_res = modify_or_place_sl(
                symbol=symbol,
                new_trigger_price=sl,
                quantity=filled_qty,
                transaction_type=exit_dir,
                product="MIS"
            )
            sl_id = sl_res.get("order_id") if sl_res.get("status") == "success" else None
            if not sl_id:
                transition_trade(symbol, "SL_FAILED", event_type="SL_FAILED", reason=sl_res.get("message") or "Protective SL placement failed", source="execution", price=sl)
                add_halt_reason("MISSING_SL", f"{symbol} entry filled but protective SL placement failed.", source="order_executor")
                self.log_message(f"Protective SL placement failed for {symbol}; safety guardian will retry. Reason: {sl_res.get('message')}", is_error=True)
            else:
                transition_trade(symbol, "SL_PLACED", event_type="SL_PLACED", reason="Protective SL placed", source="execution", sl_order_id=sl_id, order_id=sl_id, price=sl)
                transition_trade(symbol, "ACTIVE", event_type="TRADE_ACTIVE", reason="Trade active with protective SL", source="execution")
            
            with self.lock:
                self.active_trades[symbol] = {
                    "entry": fill_price,
                    "qty": filled_qty,
                    "direction": direction,
                    "sl": sl,
                    "target": target,
                    "entry_id": order_id,
                    "target_id": None,
                    "sl_id": sl_id,
                    "sl_unprotected": sl_id is None,
                    "strategy": strategy,
                    "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                self.save_active_trades()
                
            self.log_message(f"🚀 LIVE ENTRY FILLED: {direction} {qty} {symbol} @ ₹{fill_price:.2f}. SL: ₹{sl:.2f}, Target: ₹{target:.2f}, Order ID: {order_id}")
            
        except Exception as e:
            if order_id:
                transition_trade(symbol, "ENTRY_REJECTED", event_type="ENTRY_REJECTED", reason=str(e), source="execution", order_id=order_id)
                entry_error_cooldown(symbol, strategy, "Entry routing error", source="execution")
            else:
                append_event("ENTRY_REJECTED", symbol=symbol, strategy=strategy, direction=direction, state="ENTRY_REJECTED", qty=qty, price=price, reason=str(e), source="execution")
            self.log_message(f"Order routing failed for {symbol}: {e}", is_error=True)
            handle_auth_failure(e)

    def log_trade_to_journal(self, symbol, direction, entry, exit, qty, strategy, reason):
        """Records completed trades into the structured JSONL journal."""
        try:
            pnl = (exit - entry) * qty if direction == "BUY" else (entry - exit) * qty
            record_trade_close(symbol, direction, entry, exit, qty, strategy, reason)
            self.log_message(f"Logged trade exit for {symbol} to JSONL journal. PnL: ₹{pnl:.2f}")
            return pnl
        except Exception as e:
            self.log_message(f"Failed to write trade journal entry: {e}", is_error=True)
            return 0.0

    def close_active_trade_record(self, symbol, exit_price, reason):
        """Clears local state tracking records and logs exit data to journal."""
        trade = self.active_trades.get(symbol)
        if not trade:
            return
            
        # Log metrics to structured journal
        pnl = self.log_trade_to_journal(
            symbol=symbol,
            direction=trade["direction"],
            entry=trade["entry"],
            exit=exit_price,
            qty=trade["qty"],
            strategy=trade["strategy"],
            reason=reason
        )
        
        apply_exit_cooldown(symbol, trade.get("strategy", ""), reason, pnl, source="execution")
        if hasattr(self, "refresh_cooldowns"):
            self.refresh_cooldowns()
        state = get_trade_state(symbol) or {}
        if state.get("state") not in {"EXIT_REQUESTED", "EXIT_FAILED"}:
            transition_trade(symbol, "EXIT_REQUESTED", event_type="EXIT_REQUESTED", reason=reason, source="execution", price=exit_price)
        transition_trade(symbol, "EXIT_FILLED", event_type="EXIT_FILLED", reason=reason, source="execution", price=exit_price)
        close_trade(symbol, reason=reason, source="execution")
        
        with self.lock:
            if symbol in self.active_trades:
                del self.active_trades[symbol]
            self.save_active_trades()
            
        self.log_message(f"🔴 TRADE EXIT: {symbol} @ ₹{exit_price:.2f} — Reason: {reason}")
