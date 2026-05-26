from kite_order_manager import exit_single_position, modify_or_place_sl

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
        adr_absolute = metrics.get("adr_absolute", 0.0) if metrics else 0.0
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
            if self.dry_run:
                self.close_active_trade_record(symbol, target, "Target Hit (Simulated)")
            else:
                # Real order exit: The target limit order should fill, reconciler will clean state
                pass
        elif sl_hit:
            self.log_message(f"Stop-loss breach detected for {symbol} @ ₹{ltp} (SL: ₹{sl})")
            if self.dry_run:
                self.close_active_trade_record(symbol, sl, "Stop Loss Hit (Simulated)")
            else:
                # Live fallback exit triggered manually if trigger slips
                try:
                    exit_single_position(symbol)
                    self.close_active_trade_record(symbol, ltp, "Stop Loss Hit (Live)")
                except Exception as e:
                    self.log_message(f"Live exit routing failed during SL breach for {symbol}: {e}", is_error=True)
