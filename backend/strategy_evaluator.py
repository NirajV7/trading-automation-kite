import os
import json
import time
from datetime import datetime, time as datetime_time
from config import REQUIRE_MANUAL_APPROVAL
from kite_utils import round_to_tick

class StrategyEvaluatorMixin:
    def evaluate_strategy_signals(self, symbol, current_price, metrics):
        """
        Evaluates signals for scan watchlists.
        1. ORB Breakout: Current price crosses 15m high/low boundaries.
        2. Volumetric Radar Spike: Relies on external spike detection callbacks.
        """
        # Block entry if maximum core positions are already reached
        if len(self.active_trades) >= 3:
            return
            
        # Block if cooldown timer is active
        if symbol in self.cooldowns and time.time() < self.cooldowns[symbol]:
            return
            
        # Check if already holding position
        if symbol in self.active_trades:
            return

        # -------------------------------------------------------------
        # Gate 1: Time Guard (09:30 AM to 03:00 PM)
        # -------------------------------------------------------------
        now_time = datetime.now().time()
        if now_time < datetime_time(9, 30, 0) or now_time >= datetime_time(15, 0, 0):
            return

        # -------------------------------------------------------------
        # Watchlist Load & Validation
        # -------------------------------------------------------------
        from config import WATCHLIST_FILE
        watchlist = {"buy": [], "sell": []}
        if os.path.exists(WATCHLIST_FILE):
            try:
                with open(WATCHLIST_FILE, "r") as f:
                    watchlist = json.load(f)
            except Exception as e:
                self.log_message(f"Error loading watchlist: {e}", is_error=True)

        def clean_sym(s):
            return s.replace("NSE:", "").replace("-EQ", "").replace("-BE", "").upper()

        buy_watchlist = [clean_sym(s) for s in watchlist.get("buy", [])]
        sell_watchlist = [clean_sym(s) for s in watchlist.get("sell", [])]

        normalized_symbol = clean_sym(symbol)
        is_buy_candidate = normalized_symbol in buy_watchlist
        is_sell_candidate = normalized_symbol in sell_watchlist

        if not is_buy_candidate and not is_sell_candidate:
            return

        # Extract indicators from live market telemetry
        ema20_5m = metrics.get("ema20_5m")
        ema50_5m = metrics.get("ema50_5m")
        ema200_5m = metrics.get("ema200_5m")
        vwap_5m = metrics.get("vwap_5m")
        rsi_5m = metrics.get("rsi_5m")
        
        adr_absolute = metrics.get("adr_absolute", 0.0)
        today_open = metrics.get("today_open")
        today_high = metrics.get("today_high")
        today_low = metrics.get("today_low")
        
        buy_quantity_depth = metrics.get("buy_quantity", 0.0)
        sell_quantity_depth = metrics.get("sell_quantity", 0.0)
        
        active_vol_15m = metrics.get("active_vol_15m", 0.0)
        avg_vol_15m = metrics.get("avg_vol_15m", 0.0)
        active_vol_5m = metrics.get("active_vol_5m", 0.0)
        avg_vol_5m = metrics.get("avg_vol_5m", 0.0)

        orb = self.orb_ranges.get(symbol)
        if not orb:
            return
            
        high_boundary = orb["high"]
        low_boundary = orb["low"]

        # -------------------------------------------------------------
        # evaluate LONG / BUY setups
        # -------------------------------------------------------------
        if is_buy_candidate and current_price > high_boundary:
            # Gate 2: VWAP Anchor
            if vwap_5m is not None and current_price <= vwap_5m:
                return

            # Gate 3: EMA Alignment (EMA 20 > EMA 50 & Price > EMA 200)
            if ema20_5m is not None and ema50_5m is not None and ema200_5m is not None:
                if not (ema20_5m > ema50_5m and current_price > ema200_5m):
                    return

            # Gate 4: RSI Momentum Guard (50 <= RSI <= 70)
            if rsi_5m is not None and (rsi_5m < 50.0 or rsi_5m > 70.0):
                return

            # Gate 6: Volume Expansion
            minute = datetime.now().minute
            elapsed_5m_candles = (minute % 15) // 5 + 1
            if avg_vol_15m > 0:
                target_vol = 0.5 * elapsed_5m_candles * avg_vol_15m
                if active_vol_15m < target_vol:
                    return
            else:
                # Fallback to 5m baseline
                if avg_vol_5m > 0 and active_vol_5m < (avg_vol_5m * 1.5):
                    return

            # Gate 7: Tick Spread Skew (Buyer Dominance >= 1.15x)
            if sell_quantity_depth > 0:
                ratio = buy_quantity_depth / sell_quantity_depth
                if ratio < 1.15:
                    return

            # Gate 8: ADR Range Exhaustion (consumed <= 70% of ADR)
            low_ref = today_low if today_low is not None else current_price
            consumed = current_price - low_ref
            if adr_absolute > 0:
                exhaustion_pct = (consumed / adr_absolute) * 100.0
                if exhaustion_pct > 70.0:
                    self.log_message(f"Scan {symbol}: LONG failed Gate 8 (ADR exhausted: {exhaustion_pct:.1f}% > 70%)")
                    return
            else:
                if current_price > low_ref * 1.015:
                    return

            # Set SL at low of the range or tight 1.5% fallback
            sl_price = max(low_boundary, current_price * 0.985)
            sl_price = round_to_tick(sl_price)
            
            # Target at 1:2 risk-to-reward ratio
            risk_width = current_price - sl_price
            target_price = round_to_tick(current_price + (2.0 * risk_width))
            
            qty = self.calculate_position_size(symbol, current_price, sl_price)
            if qty > 0:
                self.log_message(f"🟢 CONVERGENCE PERFECT - ORB BUY triggered for {symbol} at {current_price}")
                if REQUIRE_MANUAL_APPROVAL:
                    from telegram_bot import send_signal_approval_request
                    send_signal_approval_request(symbol, "BUY", qty, current_price, sl_price, target_price, "ORB", dry_run=self.dry_run)
                    self.cooldowns[symbol] = time.time() + 300.0
                else:
                    if self.dry_run:
                        self.trigger_mock_order_placement(symbol, "BUY", qty, current_price, sl_price, target_price, "ORB")
                    else:
                        self.execute_live_order_placement(symbol, "BUY", qty, current_price, sl_price, target_price, "ORB")
                    
        # -------------------------------------------------------------
        # evaluate SHORT / SELL setups
        # -------------------------------------------------------------
        elif is_sell_candidate and current_price < low_boundary:
            # Gate 2: VWAP Anchor
            if vwap_5m is not None and current_price >= vwap_5m:
                return

            # Gate 3: EMA Alignment (EMA 20 < EMA 50 & Price < EMA 200)
            if ema20_5m is not None and ema50_5m is not None and ema200_5m is not None:
                if not (ema20_5m < ema50_5m and current_price < ema200_5m):
                    return

            # Gate 4: RSI Momentum Guard (30 <= RSI <= 50)
            if rsi_5m is not None and (rsi_5m < 30.0 or rsi_5m > 50.0):
                return

            # Gate 6: Volume Expansion
            minute = datetime.now().minute
            elapsed_5m_candles = (minute % 15) // 5 + 1
            if avg_vol_15m > 0:
                target_vol = 0.5 * elapsed_5m_candles * avg_vol_15m
                if active_vol_15m < target_vol:
                    return
            else:
                # Fallback to 5m baseline
                if avg_vol_5m > 0 and active_vol_5m < (avg_vol_5m * 1.5):
                    return

            # Gate 7: Tick Spread Skew (Seller Dominance >= 1.15x)
            if buy_quantity_depth > 0:
                ratio = sell_quantity_depth / buy_quantity_depth
                if ratio < 1.15:
                    return

            # Gate 8: ADR Range Exhaustion (consumed <= 70% of ADR)
            high_ref = today_high if today_high is not None else current_price
            consumed = high_ref - current_price
            if adr_absolute > 0:
                exhaustion_pct = (consumed / adr_absolute) * 100.0
                if exhaustion_pct > 70.0:
                    self.log_message(f"Scan {symbol}: SHORT failed Gate 8 (ADR exhausted: {exhaustion_pct:.1f}% > 70%)")
                    return
            else:
                if current_price < high_ref * 0.985:
                    return

            sl_price = min(high_boundary, current_price * 1.015)
            sl_price = round_to_tick(sl_price)
            
            risk_width = sl_price - current_price
            target_price = round_to_tick(current_price - (2.0 * risk_width))
            
            qty = self.calculate_position_size(symbol, current_price, sl_price)
            if qty > 0:
                self.log_message(f"🟢 CONVERGENCE PERFECT - ORB SELL triggered for {symbol} at {current_price}")
                if REQUIRE_MANUAL_APPROVAL:
                    from telegram_bot import send_signal_approval_request
                    send_signal_approval_request(symbol, "SELL", qty, current_price, sl_price, target_price, "ORB", dry_run=self.dry_run)
                    self.cooldowns[symbol] = time.time() + 300.0
                else:
                    if self.dry_run:
                        self.trigger_mock_order_placement(symbol, "SELL", qty, current_price, sl_price, target_price, "ORB")
                    else:
                        self.execute_live_order_placement(symbol, "SELL", qty, current_price, sl_price, target_price, "ORB")
