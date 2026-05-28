from kite_order_manager import exit_single_position, modify_or_place_sl
from order_state_machine import transition_trade
from trade_journal import append_event

class PositionMonitorMixin:
    def process_live_price_update(self, symbol, ltp, metrics=None):
        """Checks active target and SL conditions and fires exit routing on breaches."""
        trade = self.active_trades.get(symbol)
        if not trade:
            return
            
        direction = trade["direction"]
        sl = trade["sl"]
        target = trade["target"]
        
        # Check target breach
        target_hit = (direction == "BUY" and ltp >= target) or (direction == "SELL" and ltp <= target)
        # Check stop loss breach
        sl_hit = (direction == "BUY" and ltp <= sl) or (direction == "SELL" and ltp >= sl)
        
        # Trail Stop Loss to break-even if >= 70% of ADR expansion is achieved
        adr_absolute = metrics.get("adr_absolute") if metrics else 0.0
        if adr_absolute is None:
            adr_absolute = 0.0
        already_trailed = trade.get("already_trailed", False)
        if not already_trailed and adr_absolute > 0:
            entry = trade["entry"]
            expansion = (ltp - entry) if direction == "BUY" else (entry - ltp)
            if expansion >= 0.70 * adr_absolute:
                new_sl = entry
                self.log_message(f"🏆 ADR expansion >= 70% achieved for {symbol}. Trailing stop loss to break-even (cost: ₹{new_sl:.2f}).")
                trade["already_trailed"] = True
                trade["sl"] = new_sl
                self.save_active_trades()
                
                # If live, modify stop loss order on Kite
                if not self.dry_run:
                    try:
                        sl_id = trade.get("sl_id")
                        if sl_id:
                            modify_or_place_sl(
                                symbol=symbol,
                                new_trigger_price=new_sl,
                                sl_order_id=sl_id,
                                quantity=trade["qty"],
                                transaction_type="SELL" if direction == "BUY" else "BUY"
                            )
                    except Exception as e:
                        self.log_message(f"Failed to trail SL on Kite: {e}", is_error=True)

        if target_hit:
            self.log_message(f"Target limit breach detected for {symbol} @ ₹{ltp} (Target: ₹{target})")
            append_event("TARGET_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, reason="Virtual target hit", source="position_monitor")
            if self.dry_run:
                self.close_active_trade_record(symbol, target, "Target Hit (Simulated)")
            else:
                try:
                    transition_trade(symbol, "EXIT_REQUESTED", event_type="EXIT_REQUESTED", reason="Virtual target hit", source="position_monitor", price=ltp)
                    res = exit_single_position(symbol)
                    if res.get("status") == "success":
                        self.close_active_trade_record(symbol, ltp, "Virtual Target Hit (Live)")
                    else:
                        transition_trade(symbol, "EXIT_FAILED", event_type="EXIT_FAILED", reason=res.get("message"), source="position_monitor", price=ltp)
                        self.log_message(f"Live target exit not confirmed for {symbol}: {res.get('message')}", is_error=True)
                except Exception as e:
                    transition_trade(symbol, "EXIT_FAILED", event_type="EXIT_FAILED", reason=str(e), source="position_monitor", price=ltp)
                    self.log_message(f"Live exit routing failed during target breach for {symbol}: {e}", is_error=True)
        elif sl_hit:
            self.log_message(f"Stop-loss breach detected for {symbol} @ ₹{ltp} (SL: ₹{sl})")
            append_event("SL_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, reason="Stop loss hit", source="position_monitor")
            if self.dry_run:
                self.close_active_trade_record(symbol, sl, "Stop Loss Hit (Simulated)")
            else:
                # Check if Zerodha's SL order already triggered — if yes, skip manual exit to prevent double sell
                sl_id = trade.get("sl_id")
                sl_already_fired = False
                if sl_id:
                    try:
                        orders = self.kite.orders()
                        for o in orders:
                            if o.get("order_id") == sl_id and o.get("status") == "COMPLETE":
                                sl_already_fired = True
                                break
                    except Exception:
                        pass

                if sl_already_fired:
                    # SL order already executed on Zerodha — just clean up local state, no manual exit needed
                    self.log_message(f"SL order {sl_id} already fired on Zerodha for {symbol}. Skipping manual exit.")
                    self.close_active_trade_record(symbol, ltp, "Stop Loss Hit (Live)")
                else:
                    # SL order hasn't triggered yet (slipped) — fire manual fallback exit
                    try:
                        transition_trade(symbol, "EXIT_REQUESTED", event_type="EXIT_REQUESTED", reason="SL fallback exit", source="position_monitor", price=ltp)
                        exit_single_position(symbol)
                        self.close_active_trade_record(symbol, ltp, "Stop Loss Hit (Live)")
                    except Exception as e:
                        transition_trade(symbol, "EXIT_FAILED", event_type="EXIT_FAILED", reason=str(e), source="position_monitor", price=ltp)
                        self.log_message(f"Live exit routing failed during SL breach for {symbol}: {e}", is_error=True)
