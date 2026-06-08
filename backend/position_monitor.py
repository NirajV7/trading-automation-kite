from kite_order_manager import exit_single_position, modify_or_place_sl, get_position_pnl
from market_data_guard import confirm_exit_trigger
from temporary_trade_controls import TEMPORARY_PROFIT_REASON, calculate_trade_pnl, confirm_temporary_profit_exit, temporary_profit_booking_enabled, temporary_profit_threshold
from order_state_machine import begin_exit, finish_exit, transition_trade, release_exit_lock
from trade_journal import append_event
from active_trade_store import ActiveTradeStoreError, upsert_trade

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
                if self.dry_run:
                    self.save_active_trades()
                else:
                    try:
                        upsert_trade(symbol, trade, source="position_monitor")
                    except ActiveTradeStoreError as e:
                        self.log_message(f"Failed to persist trailed SL for {symbol}: {e}", is_error=True)
                
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

        profit_pnl = calculate_trade_pnl(trade.get("entry"), ltp, trade.get("qty"), direction)
        if temporary_profit_booking_enabled() and profit_pnl >= temporary_profit_threshold():
            confirm = {"confirmed": True, "ltp": ltp, "pnl": profit_pnl, "source": "cache", "stale": False}
            if not self.dry_run:
                confirm = confirm_temporary_profit_exit(symbol, trade, ltp)
                if not confirm.get("confirmed"):
                    msg = f"Exit skipped: stale cache not confirmed for {symbol} temporary profit (cached ₹{ltp}, fresh {confirm.get('ltp')}, pnl {confirm.get('pnl')}, reason: {confirm.get('reason')})"
                    self.log_message(msg, is_error=True)
                    append_event("EXIT_SKIPPED", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, pnl=profit_pnl, reason=msg, source="position_monitor")
                    return
            confirmed_ltp = confirm.get("ltp") or ltp
            confirmed_pnl = confirm.get("pnl") if confirm.get("pnl") is not None else profit_pnl
            self.log_message(f"Temporary profit booking detected for {symbol}: PnL ₹{confirmed_pnl:.2f} @ ₹{confirmed_ltp}")
            append_event("PROFIT_BOOKING_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=confirmed_ltp, pnl=confirmed_pnl, reason=TEMPORARY_PROFIT_REASON, source="position_monitor")
            if self.dry_run:
                self.close_active_trade_record(symbol, confirmed_ltp, f"{TEMPORARY_PROFIT_REASON} (Simulated)")
            else:
                try:
                    gate = begin_exit(symbol, TEMPORARY_PROFIT_REASON, "position_monitor", price=confirmed_ltp)
                    if not gate.get("ok"):
                        self.log_message(f"Exit already in progress for {symbol}: {gate.get('message')}")
                        return
                    try:
                        res = exit_single_position(symbol)
                        if res.get("status") == "success":
                            exit_price = res.get("exit_price") or confirmed_ltp
                            finish_exit(symbol, True, "Temporary profit booking exit confirmed", "position_monitor", price=exit_price, order_id=res.get("order_id"))
                            self.close_active_trade_record(symbol, exit_price, f"{TEMPORARY_PROFIT_REASON} (Live)", realized_pnl=res.get("realized_pnl"), order_id=res.get("order_id"), pnl_pending=res.get("realized_pnl") is None)
                        else:
                            finish_exit(symbol, False, res.get("message"), "position_monitor", price=confirmed_ltp)
                            self.log_message(f"Live temporary profit exit not confirmed for {symbol}: {res.get('message')}", is_error=True)
                    except Exception:
                        release_exit_lock(symbol)
                        raise
                except Exception as e:
                    finish_exit(symbol, False, str(e), "position_monitor", price=confirmed_ltp)
                    self.log_message(f"Live exit routing failed during temporary profit booking for {symbol}: {e}", is_error=True)
            return

        if target_hit:
            confirm = {"confirmed": True, "ltp": ltp, "source": "cache", "stale": False}
            if not self.dry_run:
                confirm = confirm_exit_trigger(symbol, direction, target, "target", ltp)
                if not confirm.get("confirmed"):
                    msg = f"Exit skipped: stale cache not confirmed for {symbol} target (cached ₹{ltp}, fresh {confirm.get('ltp')}, reason: {confirm.get('reason')})"
                    self.log_message(msg, is_error=True)
                    append_event("EXIT_SKIPPED", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, reason=msg, source="position_monitor")
                    return
            confirmed_ltp = confirm.get("ltp") or ltp
            self.log_message(f"Target limit breach detected for {symbol} @ ₹{confirmed_ltp} (Target: ₹{target})")
            append_event("TARGET_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=confirmed_ltp, reason="Virtual target hit", source="position_monitor")
            if self.dry_run:
                self.close_active_trade_record(symbol, target, "Target Hit (Simulated)")
            else:
                try:
                    gate = begin_exit(symbol, "Virtual target hit", "position_monitor", price=confirmed_ltp)
                    if not gate.get("ok"):
                        self.log_message(f"Exit already in progress for {symbol}: {gate.get('message')}")
                        return
                    try:
                        res = exit_single_position(symbol)
                        if res.get("status") == "success":
                            exit_price = res.get("exit_price") or confirmed_ltp
                            finish_exit(symbol, True, "Virtual target exit confirmed", "position_monitor", price=exit_price, order_id=res.get("order_id"))
                            self.close_active_trade_record(symbol, exit_price, "Virtual Target Hit (Live)", realized_pnl=res.get("realized_pnl"), order_id=res.get("order_id"), pnl_pending=res.get("realized_pnl") is None)
                        else:
                            finish_exit(symbol, False, res.get("message"), "position_monitor", price=confirmed_ltp)
                            self.log_message(f"Live target exit not confirmed for {symbol}: {res.get('message')}", is_error=True)
                    except Exception:
                        release_exit_lock(symbol)
                        raise
                except Exception as e:
                    finish_exit(symbol, False, str(e), "position_monitor", price=confirmed_ltp)
                    self.log_message(f"Live exit routing failed during target breach for {symbol}: {e}", is_error=True)
        elif sl_hit:
            self.log_message(f"Stop-loss breach detected for {symbol} @ ₹{ltp} (SL: ₹{sl})")
            if self.dry_run:
                append_event("SL_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, reason="Stop loss hit", source="position_monitor")
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
                    append_event("SL_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, reason="Stop loss hit", source="position_monitor")
                    self.close_active_trade_record(symbol, ltp, "Stop Loss Hit (Live)", realized_pnl=get_position_pnl(self.kite, symbol), order_id=sl_id)
                else:
                    # SL order hasn't triggered yet (slipped) — fire manual fallback exit
                    try:
                        confirm = confirm_exit_trigger(symbol, direction, sl, "sl", ltp)
                        if not confirm.get("confirmed"):
                            msg = f"Exit skipped: stale cache not confirmed for {symbol} SL fallback (cached ₹{ltp}, fresh {confirm.get('ltp')}, reason: {confirm.get('reason')})"
                            self.log_message(msg, is_error=True)
                            append_event("EXIT_SKIPPED", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=ltp, reason=msg, source="position_monitor")
                            return
                        confirmed_ltp = confirm.get("ltp") or ltp
                        append_event("SL_HIT", symbol=symbol, strategy=trade.get("strategy"), direction=direction, state="ACTIVE", qty=trade.get("qty"), price=confirmed_ltp, reason="Stop loss hit", source="position_monitor")
                        gate = begin_exit(symbol, "SL fallback exit", "position_monitor", price=confirmed_ltp)
                        if not gate.get("ok"):
                            self.log_message(f"Exit already in progress for {symbol}: {gate.get('message')}")
                            return
                        try:
                            res = exit_single_position(symbol)
                            if res.get("status") == "success":
                                exit_price = res.get("exit_price") or confirmed_ltp
                                finish_exit(symbol, True, "SL fallback exit confirmed", "position_monitor", price=exit_price, order_id=res.get("order_id"))
                                self.close_active_trade_record(symbol, exit_price, "Stop Loss Hit (Live)", realized_pnl=res.get("realized_pnl"), order_id=res.get("order_id"), pnl_pending=res.get("realized_pnl") is None)
                            else:
                                finish_exit(symbol, False, res.get("message"), "position_monitor", price=confirmed_ltp)
                                self.log_message(f"Live exit not confirmed during SL breach for {symbol}: {res.get('message')}", is_error=True)
                        except Exception:
                            release_exit_lock(symbol)
                            raise
                    except Exception as e:
                        finish_exit(symbol, False, str(e), "position_monitor", price=confirmed_ltp if 'confirmed_ltp' in locals() else ltp)
                        self.log_message(f"Live exit routing failed during SL breach for {symbol}: {e}", is_error=True)
