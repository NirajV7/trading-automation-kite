from datetime import datetime

from config import RISK_PER_TRADE
from kite_auth_manager import get_kite_client
from kite_order_manager import modify_or_place_sl
from order_state_machine import reconcile_trade, transition_trade
from kite_utils import round_to_tick, handle_auth_failure

class ReconcilerMixin:
    def audit_active_positions_with_broker(self):
        """
        Reconciles system memory logs with broker positions.
        If a position was closed on Kite, clean up local cache.
        If a target or SL order is missing, self-heals by replacing them.
        """
        if self.dry_run:
            # Reconciler simulator is bypassed during test runs
            return

        try:
            self.kite = get_kite_client()
            positions = self.kite.positions().get("net", [])
            orders = self.kite.orders()
            
            broker_net = {p["tradingsymbol"]: int(p["quantity"]) for p in positions if int(p["quantity"]) != 0}
            
            # 1. Check for local positions that are closed on the broker
            for sym in list(self.active_trades.keys()):
                if sym not in broker_net:
                    self.log_message(f"Sync: Ticker {sym} closed on Zerodha. Resolving active trade cache.")
                    self.close_active_trade_record(sym, self.active_trades[sym]["entry"], "Manual Closed (Kite)")
                    
            # 2. Check for missing Stop-Loss orders for active positions
            open_statuses = ["OPEN", "TRIGGER PENDING", "VALIDATION PENDING"]
            for sym, qty in broker_net.items():
                trade = self.active_trades.get(sym)
                if not trade:
                    # System discovered a position it didn't open. Re-import and establish safety brackets
                    self.log_message(f"Sync: Discovered untracked active position for {sym}. Importing...")
                    avg_price = 0.0
                    for p in positions:
                        if p["tradingsymbol"] == sym:
                            avg_price = float(p["average_price"])
                            break
                    
                    direction = "BUY" if qty > 0 else "SELL"
                    # Default tight safety stop (1.5%)
                    sl_dist = avg_price * 0.015
                    # Enforce NJ's max risk limit from config
                    max_sl_dist = RISK_PER_TRADE / abs(qty)
                    if sl_dist > max_sl_dist:
                        sl_dist = max_sl_dist
                    
                    sl_price = round_to_tick(avg_price - sl_dist) if direction == "BUY" else round_to_tick(avg_price + sl_dist)
                    target_price = round_to_tick(avg_price * 1.03) if direction == "BUY" else round_to_tick(avg_price * 0.97)
                    
                    # Place live bracket stop
                    exit_dir = "SELL" if direction == "BUY" else "BUY"
                    sl_res = modify_or_place_sl(
                        symbol=sym,
                        new_trigger_price=sl_price,
                        quantity=abs(qty),
                        transaction_type=exit_dir,
                        product="MIS"
                    )
                    sl_id = sl_res.get("order_id") if sl_res.get("status") == "success" else None
                    reconcile_trade(sym, direction, abs(qty), avg_price, sl_price, target_price, sl_order_id=sl_id, strategy="RECONCILED")
                    
                    with self.lock:
                        self.active_trades[sym] = {
                            "entry": avg_price,
                            "qty": abs(qty),
                            "direction": direction,
                            "sl": sl_price,
                            "target": target_price,
                            "sl_id": sl_id,
                            "sl_unprotected": sl_id is None,
                            "strategy": "RECONCILED",
                            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        self.save_active_trades()
                        
                else:
                    # Reconcile SL order ID if not tracked locally or canceled/rejected on Kite
                    sl_id = trade.get("sl_id")
                    sl_order_exists = False
                    discovered_sl_id = None
                    exit_dir = "SELL" if trade["direction"] == "BUY" else "BUY"
                    for o in orders:
                        if (
                            o.get("tradingsymbol") == sym and
                            o.get("status") in open_statuses and
                            o.get("transaction_type") == exit_dir and
                            o.get("order_type") == "LIMIT"
                        ):
                            try:
                                self.kite.cancel_order(variety=o.get("variety", "regular"), order_id=o.get("order_id"))
                                self.log_message(f"Sync: Cancelled stale target LIMIT order {o.get('order_id')} for {sym}.")
                            except Exception as cancel_err:
                                self.log_message(f"Sync: Failed cancelling stale target LIMIT for {sym}: {cancel_err}", is_error=True)

                    if sl_id:
                        for o in orders:
                            if o.get("order_id") == sl_id and o.get("status") in open_statuses:
                                sl_order_exists = True
                                discovered_sl_id = sl_id
                                break
                    else:
                        for o in orders:
                            if (
                                o.get("tradingsymbol") == sym and
                                o.get("status") in open_statuses and
                                o.get("transaction_type") == exit_dir and
                                o.get("order_type") in ["SL", "SL-M"]
                            ):
                                sl_order_exists = True
                                discovered_sl_id = o.get("order_id")
                                break

                    if sl_order_exists and discovered_sl_id and trade.get("sl_id") != discovered_sl_id:
                        trade["sl_id"] = discovered_sl_id
                        trade["sl_unprotected"] = False
                        transition_trade(sym, "SL_PLACED", event_type="SL_PLACED", reason="Discovered active SL during reconciliation", source="reconciler", sl_order_id=discovered_sl_id, order_id=discovered_sl_id, price=trade.get("sl"))
                        transition_trade(sym, "ACTIVE", event_type="TRADE_ACTIVE", reason="Reconciled SL active", source="reconciler")
                        self.save_active_trades()
                                
                    if not sl_order_exists:
                        self.log_message(f"Sync: SL order missing for held position {sym}. Replacing bracket safety order...")
                        exit_dir = "SELL" if trade["direction"] == "BUY" else "BUY"
                        sl_res = modify_or_place_sl(
                            symbol=sym,
                            new_trigger_price=trade["sl"],
                            quantity=trade["qty"],
                            transaction_type=exit_dir,
                            product="MIS"
                        )
                        if sl_res.get("status") == "success":
                            trade["sl_id"] = sl_res.get("order_id")
                            trade["sl_unprotected"] = False
                            transition_trade(sym, "SL_PLACED", event_type="SL_PLACED", reason="Replaced missing SL during reconciliation", source="reconciler", sl_order_id=trade["sl_id"], order_id=trade["sl_id"], price=trade.get("sl"))
                            transition_trade(sym, "ACTIVE", event_type="TRADE_ACTIVE", reason="Reconciled SL active", source="reconciler")
                            self.save_active_trades()
                            self.log_message(f"Sync: Successfully replaced SL order ID to {trade['sl_id']}")
                        else:
                            transition_trade(sym, "SL_FAILED", event_type="SL_FAILED", reason=sl_res.get("message"), source="reconciler", price=trade.get("sl"))
                            
        except Exception as e:
            self.log_message(f"Reconciliation check failed: {e}", is_error=True)
            handle_auth_failure(e)
