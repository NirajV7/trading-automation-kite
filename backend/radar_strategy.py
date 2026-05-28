import os
import json
import time
from datetime import datetime
from datetime import time as datetime_time
import config
from kite_utils import round_to_tick
from risk_governor import can_open_trade
from symbol_cooldowns import get_active_cooldown
from trade_journal import append_event

class RadarStrategyMixin:
    def load_radar_candidates(self):
        """Loads persistent radar candidate states from JSON."""
        if os.path.exists(config.RADAR_CANDIDATES_FILE):
            try:
                with open(config.RADAR_CANDIDATES_FILE, "r") as f:
                    self.radar_candidates = json.load(f)
            except Exception as e:
                self.log_message(f"Error loading radar candidates: {e}", is_error=True)
                self.radar_candidates = {}
        else:
            self.radar_candidates = {}

    def save_radar_candidates(self):
        """Persists radar candidate states to JSON atomically."""
        temp_file = f"{config.RADAR_CANDIDATES_FILE}.tmp"
        try:
            with open(temp_file, "w") as f:
                json.dump(self.radar_candidates, f, indent=4)
            os.replace(temp_file, config.RADAR_CANDIDATES_FILE)
        except Exception as e:
            self.log_message(f"Error saving radar candidates: {e}", is_error=True)
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    def evaluate_radar_signals(self, symbol, ltp, metrics):
        """
        Executes Nifty 50 Volume Spike Pullback Strategy state machine.
        1. Detection (1m closed volume >= 3.0x, momentum >= 0.25%)
        2. Pullback Zone (Hit 5m EMA20)
        3. Volume Contraction & ORB/SpikeOpen/VWAP Invalidation
        4. Resumption Trigger (Cross prev closed 5m High/Low)
        """
        now_time = datetime.now().time()
        if now_time < datetime_time(9, 30, 0) or now_time >= datetime_time(15, 0, 0):
            return

        # If we are already holding this symbol, clean up candidate to release state tracking
        if symbol in self.active_trades:
            if symbol in self.radar_candidates:
                del self.radar_candidates[symbol]
                self.save_radar_candidates()
            return

        # Block if cooldown timer is active
        cooldown = get_active_cooldown(symbol)
        if cooldown:
            append_event("SIGNAL_BLOCKED", symbol=symbol, strategy="RADAR", state="BLOCKED", reason=f"Cooldown active: {cooldown.get('reason')}", source="cooldown")
            if symbol in self.radar_candidates:
                del self.radar_candidates[symbol]
                self.save_radar_candidates()
            return

        # -------------------------------------------------------------
        # Phase 1: Detection (The Spike)
        # -------------------------------------------------------------
        if symbol not in self.radar_candidates:
            governor_gate = can_open_trade(symbol, "RADAR", active_trades=self.active_trades)
            if not governor_gate.get("allowed"):
                append_event("SIGNAL_BLOCKED", symbol=symbol, strategy="RADAR", state="BLOCKED", reason=governor_gate.get("message"), source="risk_governor")
                self.log_gate_failure(symbol, "risk_governor_radar", f"Risk Governor blocked radar detection for {symbol}: {governor_gate.get('message')}")
                return

            prev_open_1m = metrics.get("prev_open_1m")
            prev_close_1m = metrics.get("prev_close_1m")
            prev_volume_1m = metrics.get("prev_volume_1m")
            avg_vol_1m = metrics.get("avg_vol_1m", 0.0)

            if prev_open_1m is not None and prev_close_1m is not None and prev_volume_1m is not None and avg_vol_1m > 0:
                # Volume Ratio calculation
                vol_ratio = prev_volume_1m / avg_vol_1m
                # Price Momentum %
                price_move_pct = (abs(prev_close_1m - prev_open_1m) / prev_open_1m) * 100.0

                if vol_ratio >= config.VOLUME_SPIKE_RATIO and price_move_pct >= config.PRICE_MOMENTUM_PCT:
                    direction = "BUY" if prev_close_1m > prev_open_1m else "SELL"
                    
                    self.log_message(
                        f"📢 [RADAR] {symbol}: 1m Volume Spike Detected! "
                        f"Direction: {direction}, Vol Ratio: {vol_ratio:.1f}x, Price Move: {price_move_pct:.2f}%"
                    )

                    self.radar_candidates[symbol] = {
                        "state": "WAITING_FOR_PULLBACK",
                        "direction": direction,
                        "spike_price": prev_close_1m,
                        "spike_open": prev_open_1m,
                        "spike_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "lowest_pullback_low": ltp,
                        "highest_pullback_high": ltp,
                        "last_closed_5m_time": metrics.get("last_closed_5m_time")
                    }
                    self.save_radar_candidates()
            return

        # -------------------------------------------------------------
        # Phase 2, 3, 4: Pullback, Invalidation, Trigger
        # -------------------------------------------------------------
        cand = self.radar_candidates[symbol]
        direction = cand["direction"]
        state = cand["state"]

        # Track extreme high/low printed during pullback phase
        cand["lowest_pullback_low"] = min(cand.get("lowest_pullback_low", ltp), ltp)
        cand["highest_pullback_high"] = max(cand.get("highest_pullback_high", ltp), ltp)

        # Retrieve required 5m indicators
        ema20_5m = metrics.get("ema20_5m")

        # 1. Closed 5m Invalidation Checks (Runs once when 5m candle boundary updates)
        # Evaluated for both WAITING_FOR_PULLBACK and IN_PULLBACK states
        last_closed_5m_time = metrics.get("last_closed_5m_time")
        stored_closed_5m_time = cand.get("last_closed_5m_time")

        if last_closed_5m_time is not None and last_closed_5m_time != stored_closed_5m_time:
            cand["last_closed_5m_time"] = last_closed_5m_time
            
            prev_volume_5m = metrics.get("prev_volume_5m")
            if prev_volume_5m is None:
                prev_volume_5m = 0.0
            avg_vol_5m = metrics.get("avg_vol_5m", 0.0)
            prev_close_5m = metrics.get("prev_close_5m")
            vwap_5m = metrics.get("vwap_5m")

            # Validation A: Volume Drying Check (pullback 5m volume must be < 0.8x average)
            if avg_vol_5m > 0:
                vol_limit = avg_vol_5m * 0.8
                if prev_volume_5m >= vol_limit:
                    self.log_message(
                        f"❌ [RADAR] {symbol} Setup Invalidated: Pullback volume did not dry "
                        f"(Pullback Vol: {prev_volume_5m} >= limit: {vol_limit:.0f})"
                    )
                    del self.radar_candidates[symbol]
                    self.save_radar_candidates()
                    return

            # Validation B: Technical Levels Invalidation Check
            # Fetch 15m ORB range from memory (requires establish_single_orb_range fallback)
            orb = self.orb_ranges.get(symbol)
            if not orb:
                orb = self.establish_single_orb_range(symbol)

            if orb and prev_close_5m is not None:
                spike_open = cand["spike_open"]
                
                if direction == "BUY":
                    orb_high = orb["high"]
                    if prev_close_5m < orb_high or prev_close_5m < spike_open or (vwap_5m is not None and prev_close_5m < vwap_5m):
                        self.log_message(
                            f"❌ [RADAR] {symbol} Setup Invalidated: 5m Close {prev_close_5m:.2f} broke below "
                            f"ORB High: {orb_high:.2f}, Spike Open: {spike_open:.2f}, or VWAP: {vwap_5m}"
                        )
                        del self.radar_candidates[symbol]
                        self.save_radar_candidates()
                        return
                else: # SELL setup
                    orb_low = orb["low"]
                    if prev_close_5m > orb_low or prev_close_5m > spike_open or (vwap_5m is not None and prev_close_5m > vwap_5m):
                        self.log_message(
                            f"❌ [RADAR] {symbol} Setup Invalidated: 5m Close {prev_close_5m:.2f} broke above "
                            f"ORB Low: {orb_low:.2f}, Spike Open: {spike_open:.2f}, or VWAP: {vwap_5m}"
                        )
                        del self.radar_candidates[symbol]
                        self.save_radar_candidates()
                        return
            self.save_radar_candidates()

        # -------------------------------------------------------------
        # state: WAITING_FOR_PULLBACK -> Checks EMA20 zone touch
        # -------------------------------------------------------------
        if state == "WAITING_FOR_PULLBACK":
            if ema20_5m is not None:
                if direction == "BUY" and ltp <= ema20_5m:
                    cand["state"] = "IN_PULLBACK"
                    self.log_message(f"📉 [RADAR] {symbol}: Pullback zone reached (LTP: {ltp:.2f} <= 5m EMA20: {ema20_5m:.2f}). State: IN_PULLBACK")
                    self.save_radar_candidates()
                elif direction == "SELL" and ltp >= ema20_5m:
                    cand["state"] = "IN_PULLBACK"
                    self.log_message(f"📈 [RADAR] {symbol}: Pullback zone reached (LTP: {ltp:.2f} >= 5m EMA20: {ema20_5m:.2f}). State: IN_PULLBACK")
                    self.save_radar_candidates()

        # -------------------------------------------------------------
        # state: IN_PULLBACK -> Evaluates closed 5m filters and trigger
        # -------------------------------------------------------------
        elif state == "IN_PULLBACK":
            # 2. Tick-by-tick trigger check
            prev_high_5m = metrics.get("prev_high_5m")
            prev_low_5m = metrics.get("prev_low_5m")

            if direction == "BUY" and prev_high_5m is not None:
                if ltp > prev_high_5m:
                    # Apply final core position limits before entry
                    governor_gate = can_open_trade(symbol, "RADAR", active_trades=self.active_trades)
                    if not governor_gate.get("allowed"):
                        append_event("SIGNAL_BLOCKED", symbol=symbol, strategy="RADAR", direction="BUY", state="BLOCKED", price=ltp, reason=governor_gate.get("message"), source="risk_governor")
                        self.log_message(f"⚠️ [RADAR] Trigger condition met for {symbol} but Risk Governor blocked entry: {governor_gate.get('message')}")
                        del self.radar_candidates[symbol]
                        self.save_radar_candidates()
                        return

                    # Trigger entry!
                    sl = cand["lowest_pullback_low"]
                    # If SL low matches or is above trigger price due to noise, enforce a tight 1.5% fallback
                    if sl >= ltp:
                        sl = ltp * 0.985
                    sl = round_to_tick(sl)
                    
                    risk_width = ltp - sl
                    target = round_to_tick(ltp + (2.0 * risk_width))
                    qty = self.calculate_position_size(symbol, ltp, sl)

                    if qty > 0:
                        self.log_message(f"🚀 [RADAR] BUY Triggered for {symbol} @ ₹{ltp:.2f} (SL: ₹{sl:.2f}, Target: ₹{target:.2f}, Qty: {qty})")
                        if self.dry_run:
                            self.trigger_mock_order_placement(symbol, "BUY", qty, ltp, sl, target, "RADAR")
                        else:
                            self.execute_live_order_placement(symbol, "BUY", qty, ltp, sl, target, "RADAR")
                    
                    del self.radar_candidates[symbol]
                    self.save_radar_candidates()

            elif direction == "SELL" and prev_low_5m is not None:
                if ltp < prev_low_5m:
                    # Apply final core position limits before entry
                    governor_gate = can_open_trade(symbol, "RADAR", active_trades=self.active_trades)
                    if not governor_gate.get("allowed"):
                        append_event("SIGNAL_BLOCKED", symbol=symbol, strategy="RADAR", direction="SELL", state="BLOCKED", price=ltp, reason=governor_gate.get("message"), source="risk_governor")
                        self.log_message(f"⚠️ [RADAR] Trigger condition met for {symbol} but Risk Governor blocked entry: {governor_gate.get('message')}")
                        del self.radar_candidates[symbol]
                        self.save_radar_candidates()
                        return

                    # Trigger entry!
                    sl = cand["highest_pullback_high"]
                    if sl <= ltp:
                        sl = ltp * 1.015
                    sl = round_to_tick(sl)

                    risk_width = sl - ltp
                    target = round_to_tick(ltp - (2.0 * risk_width))
                    qty = self.calculate_position_size(symbol, ltp, sl)

                    if qty > 0:
                        self.log_message(f"🚀 [RADAR] SELL Triggered for {symbol} @ ₹{ltp:.2f} (SL: ₹{sl:.2f}, Target: ₹{target:.2f}, Qty: {qty})")
                        if self.dry_run:
                            self.trigger_mock_order_placement(symbol, "SELL", qty, ltp, sl, target, "RADAR")
                        else:
                            self.execute_live_order_placement(symbol, "SELL", qty, ltp, sl, target, "RADAR")

                    del self.radar_candidates[symbol]
                    self.save_radar_candidates()
