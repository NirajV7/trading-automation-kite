import os
import csv
import time
from datetime import datetime
from config import RISK_PER_TRADE, CAPITAL_ALLOCATION, TRADE_JOURNAL_CSV, ACTIVE_TRADES_FILE
from kite_auth_manager import get_kite_client
from kite_utils import round_to_tick, handle_auth_failure
from kite_order_manager import modify_or_place_sl

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
            return max(1, final_qty)
        except Exception as e:
            self.log_message(f"Error sizing position for {symbol}: {e}", is_error=True)
            return 0

    def trigger_mock_order_placement(self, symbol, direction, qty, price, sl, target, strategy):
        """Simulates placing and filling bracket orders instantly for dry-run trading."""
        order_id = f"MOCK_ENTRY_{int(time.time())}"
        sl_id = f"MOCK_SL_{int(time.time())}"
        target_id = f"MOCK_TARGET_{int(time.time())}"
        
        with self.lock:
            self.active_trades[symbol] = {
                "entry": price,
                "qty": qty,
                "direction": direction,
                "sl": sl,
                "target": target,
                "sl_id": sl_id,
                "target_id": target_id,
                "strategy": strategy,
                "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.save_active_trades()
            
        self.log_message(f"[DRY-RUN] Filled mock {direction} for {symbol}. Qty: {qty} @ ₹{price}, SL: ₹{sl}, Target: ₹{target}")

    def execute_live_order_placement(self, symbol, direction, qty, price, sl, target, strategy):
        """Submits real entry orders and bracket safety orders to Zerodha Kite."""
        try:
            self.kite = get_kite_client()
            
            # Place entry market order (MIS product for intraday execution leverage)
            self.log_message(f"Submitting live entry order: {direction} {qty} {symbol} MIS...")
            order_id = self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=symbol,
                transaction_type=direction,
                quantity=qty,
                product="MIS",
                order_type="MARKET",
                market_protection=-1
            )
            
            # Retrieve average fill price (wait briefly for matching engine execution)
            time.sleep(0.5)
            orders = self.kite.orders()
            fill_price = price # fallback
            for o in orders:
                if o.get("order_id") == order_id:
                    if o.get("status") == "COMPLETE":
                        fill_price = float(o.get("average_price", price))
                        break
                    else:
                        raise RuntimeError(f"Entry order {order_id} not completely filled: {o.get('status')}")
            
            # Calculate exit direction for brackets
            exit_dir = "SELL" if direction == "BUY" else "BUY"
            
            # Place target Limit Order
            self.log_message(f"Submitting target limit order: {exit_dir} {qty} {symbol} @ ₹{target}...")
            target_id = self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=symbol,
                transaction_type=exit_dir,
                quantity=qty,
                product="MIS",
                order_type="LIMIT",
                price=round_to_tick(target)
            )
            
            # Place stop-loss SL order
            self.log_message(f"Submitting stop-loss trigger order: {exit_dir} {qty} {symbol} trigger ₹{sl}...")
            sl_res = modify_or_place_sl(
                symbol=symbol,
                new_trigger_price=sl,
                quantity=qty,
                transaction_type=exit_dir,
                product="MIS"
            )
            sl_id = sl_res.get("order_id") if sl_res.get("status") == "success" else None
            
            with self.lock:
                self.active_trades[symbol] = {
                    "entry": fill_price,
                    "qty": qty,
                    "direction": direction,
                    "sl": sl,
                    "target": target,
                    "entry_id": order_id,
                    "target_id": target_id,
                    "sl_id": sl_id,
                    "strategy": strategy,
                    "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                self.save_active_trades()
                
            self.log_message(f"🚀 LIVE ENTRY FILLED: {direction} {qty} {symbol} @ ₹{fill_price:.2f}. SL: ₹{sl:.2f}, Target: ₹{target:.2f}, Order ID: {order_id}")
            
        except Exception as e:
            self.log_message(f"Order routing failed for {symbol}: {e}", is_error=True)
            handle_auth_failure(e)

    def log_trade_to_journal(self, symbol, direction, entry, exit, qty, strategy, reason):
        """Records completed trades into the CSV journal for P&L diagnostics."""
        try:
            os.makedirs(os.path.dirname(TRADE_JOURNAL_CSV), exist_ok=True)
            file_exists = os.path.exists(TRADE_JOURNAL_CSV)
            
            pnl = (exit - entry) * qty if direction == "BUY" else (entry - exit) * qty
            pnl_pct = ((exit - entry) / entry) * 100.0 if direction == "BUY" else ((entry - exit) / entry) * 100.0
            
            with open(TRADE_JOURNAL_CSV, "a", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Timestamp", "Symbol", "Direction", "EntryPrice", "ExitPrice", "Qty", "PnL_INR", "PnL_Pct", "Strategy", "Reason"])
                writer.writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    symbol,
                    direction,
                    round(entry, 2),
                    round(exit, 2),
                    qty,
                    round(pnl, 2),
                    round(pnl_pct, 2),
                    strategy,
                    reason
                ])
            self.log_message(f"Logged trade exit for {symbol} to journal CSV. PnL: ₹{pnl:.2f}")
        except Exception as e:
            self.log_message(f"Failed to write trade journal entry: {e}", is_error=True)

    def close_active_trade_record(self, symbol, exit_price, reason):
        """Clears local state tracking records and logs exit data to journal."""
        trade = self.active_trades.get(symbol)
        if not trade:
            return
            
        # Log metrics to CSV
        self.log_trade_to_journal(
            symbol=symbol,
            direction=trade["direction"],
            entry=trade["entry"],
            exit=exit_price,
            qty=trade["qty"],
            strategy=trade["strategy"],
            reason=reason
        )
        
        # Enforce entry cooldown (prevent immediate re-entry for 10 minutes)
        self.cooldowns[symbol] = time.time() + 600.0
        
        with self.lock:
            if symbol in self.active_trades:
                del self.active_trades[symbol]
            self.save_active_trades()
            
        self.log_message(f"🔴 TRADE EXIT: {symbol} @ ₹{exit_price:.2f} — Reason: {reason}")
