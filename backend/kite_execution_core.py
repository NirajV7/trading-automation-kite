import os
import json
import time
import csv
from datetime import datetime, time as datetime_time
import threading
import urllib.request
import urllib.parse

from config import (
    NIFTY_50_TICKERS,
    RISK_PER_TRADE,
    CAPITAL_ALLOCATION,
    ACTIVE_TRADES_FILE,
    TRADE_JOURNAL_CSV,
    ENGINE_LOG,
    INSTRUMENT_MAPPING_FILE,
    LIVE_MARKET_DATA_FILE,
    REQUIRE_MANUAL_APPROVAL
)
from kite_auth_manager import get_kite_client
from kite_utils import round_to_tick, handle_auth_failure
from kite_order_manager import exit_single_position, modify_or_place_sl

# -------------------------------------------------------------
# GLOBAL HELPER FOR TELEGRAM NOTIFICATIONS
# -------------------------------------------------------------
def send_telegram_alert(message):
    """
    Sends a formatted notification to the principal's iPhone Telegram Bot.
    Uses the tokens and chat ID defined in the environment.
    """
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram config missing. Alert suppressed: {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        # Format payloads with HTML tags for clean styling on the iPhone screen
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🤖 <b>KITE CORE ALERT</b>\n\n{message}",
            "parse_mode": "HTML"
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"❌ Telegram alert failed: {e}")


# -------------------------------------------------------------
# CORE EXECUTION SYSTEM CLASS
# -------------------------------------------------------------
class KiteExecutionCore:
    """
    Manages strategy evaluations (ORB & Volumetric Spikes), handles risk 
    allocation math, tracks active positions, executes orders (Dry Run or Live),
    and synchronizes execution state with Zerodha.
    """

    def __init__(self, dry_run=True):
        self.lock = threading.Lock()
        self.dry_run = dry_run
        self.kite = None
        
        # Load mappings to resolve symbol tokens during setup
        self.symbol_to_token = {}
        self.load_symbol_mappings()
        
        # Local state storage
        self.active_trades = {}  # {SYMBOL: {entry_price, qty, direction, sl, target, sl_id, target_id, strategy}}
        self.cooldowns = {}       # {SYMBOL: cooldown_end_timestamp}
        self.orb_ranges = {}      # {SYMBOL: {"high": value, "low": value}}
        
        # Load existing active trades from disk to prevent loss on restart
        self.load_active_trades()
        self.log_message(f"Execution Core initialized. Mode: {'DRY RUN' if dry_run else 'LIVE'}")

    def log_message(self, msg, is_error=False):
        """Appends logs atomically to backend/logs/engine.log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = "[ERROR]" if is_error else "[INFO]"
        log_line = f"{timestamp} {prefix} {msg}\n"
        print(f"{prefix} {msg}")
        try:
            with open(ENGINE_LOG, "a") as f:
                f.write(log_line)
        except Exception as e:
            print(f"Failed to write log line: {e}")

    def load_symbol_mappings(self):
        """Loads token mappings from cached instrument mappings file."""
        if os.path.exists(INSTRUMENT_MAPPING_FILE):
            try:
                with open(INSTRUMENT_MAPPING_FILE, "r") as f:
                    data = json.load(f)
                    self.symbol_to_token = {k: int(v) for k, v in data.get("symbol_to_token", {}).items()}
            except Exception as e:
                self.log_message(f"Error loading symbol mappings: {e}", is_error=True)

    def load_active_trades(self):
        """Reads persisted active trades from active_trades.json."""
        if os.path.exists(ACTIVE_TRADES_FILE):
            try:
                with open(ACTIVE_TRADES_FILE, "r") as f:
                    self.active_trades = json.load(f)
                self.log_message(f"Loaded {len(self.active_trades)} active trades from disk cache.")
            except Exception as e:
                self.log_message(f"Failed to load active trades: {e}", is_error=True)

    def save_active_trades(self):
        """Saves current active trades list atomically to active_trades.json."""
        try:
            temp_path = f"{ACTIVE_TRADES_FILE}.tmp"
            with open(temp_path, "w") as f:
                json.dump(self.active_trades, f, indent=4)
            os.replace(temp_path, ACTIVE_TRADES_FILE)
        except Exception as e:
            self.log_message(f"Failed to save active trades file: {e}", is_error=True)

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

    def establish_orb_ranges(self):
        """
        Fetches historical data at boot/intervals to establish Opening Range (first 15m candle)
        for all Nifty 50 tickers. Allows restarts mid-day without losing boundaries.
        """
        if self.dry_run:
            self.log_message("Establish ORB: dry-run mode active. Initializing mock ranges.")
            # For simulator testing, establish high/low parameters around arbitrary base values
            for sym in NIFTY_50_TICKERS:
                self.orb_ranges[sym] = {"high": 1000.0, "low": 980.0}
            return

        try:
            self.kite = get_kite_client()
            today = datetime.now()
            
            # Formulate start of day and end of day query parameters
            from_time = datetime.combine(today.date(), datetime_time(9, 15, 0))
            to_time = datetime.combine(today.date(), datetime_time(15, 30, 0))
            
            self.log_message("Establishing today's 15m Opening Ranges from Zerodha...")
            for sym in NIFTY_50_TICKERS:
                token = self.symbol_to_token.get(sym)
                if not token:
                    continue
                
                try:
                    candles = self.kite.historical_data(
                        instrument_token=token,
                        from_date=from_time,
                        to_date=to_time,
                        interval="15minute"
                    )
                    
                    if candles:
                        # Scan for the 09:15 AM opening 15-minute candle
                        for c in candles:
                            c_dt = c["date"]
                            # Zerodha stores dates in tz-aware objects, check hour/minute
                            if c_dt.hour == 9 and c_dt.minute == 15:
                                self.orb_ranges[sym] = {
                                    "high": float(c["high"]),
                                    "low": float(c["low"])
                                }
                                break
                except Exception as e:
                    self.log_message(f"Failed fetching historical ORB for {sym}: {e}", is_error=True)
                
                time.sleep(0.05) # Respect rate limits
            self.log_message(f"Established ORB boundaries for {len(self.orb_ranges)} tickers.")
        except Exception as e:
            self.log_message(f"Critical error establishing ORB: {e}", is_error=True)
            handle_auth_failure(e)

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
            
        alert_msg = (
            f"🟢 <b>SIMULATED ENTRY FILLED</b>\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Direction:</b> {direction}\n"
            f"<b>Quantity:</b> {qty}\n"
            f"<b>Entry Price:</b> ₹{price:.2f}\n"
            f"<b>Stop Loss:</b> ₹{sl:.2f}\n"
            f"<b>Target:</b> ₹{target:.2f}\n"
            f"<b>Strategy:</b> {strategy}"
        )
        send_telegram_alert(alert_msg)
        self.log_message(f"[DRY-RUN] Filled mock trade for {symbol}. Qty: {qty} @ ₹{price}")

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
                order_type="MARKET"
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
                
            alert_msg = (
                f"🚀 <b>LIVE ENTRY FILLED</b>\n"
                f"<b>Stock:</b> {symbol}\n"
                f"<b>Direction:</b> {direction}\n"
                f"<b>Quantity:</b> {qty}\n"
                f"<b>Fill Price:</b> ₹{fill_price:.2f}\n"
                f"<b>Stop Loss:</b> ₹{sl:.2f}\n"
                f"<b>Target:</b> ₹{target:.2f}\n"
                f"<b>Order ID:</b> {order_id}"
            )
            send_telegram_alert(alert_msg)
            self.log_message(f"Live entry executed for {symbol}. Target: {target_id}, SL: {sl_id}")
            
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
            
        alert_msg = (
            f"🔴 <b>TRADE EXIT COMPLETE</b>\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Exit Price:</b> ₹{exit_price:.2f}\n"
            f"<b>Reason:</b> {reason}"
        )
        send_telegram_alert(alert_msg)

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
                            send_telegram_alert(f"🏆 Trailed {symbol} Stop Loss to break-even (cost: ₹{new_sl:.2f}).")
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
                    # Enforce NJ's ₹2,500 max risk limit
                    max_sl_dist = 2500.0 / abs(qty)
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
                    
                    with self.lock:
                        self.active_trades[sym] = {
                            "entry": avg_price,
                            "qty": abs(qty),
                            "direction": direction,
                            "sl": sl_price,
                            "target": target_price,
                            "sl_id": sl_id,
                            "strategy": "RECONCILED",
                            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        self.save_active_trades()
                else:
                    # Verify stop loss order ID is active on broker logs
                    sl_id = trade.get("sl_id")
                    sl_active = False
                    for o in orders:
                        if o["order_id"] == sl_id and o["status"] in open_statuses:
                            sl_active = True
                            break
                            
                    if not sl_active:
                        self.log_message(f"Sync: Missing stop-loss order for {sym} detected. Healing...")
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
                            self.save_active_trades()
                            self.log_message(f"Sync: Successfully replaced SL order ID to {trade['sl_id']}")
                            
        except Exception as e:
            self.log_message(f"Reconciliation check failed: {e}", is_error=True)
            handle_auth_failure(e)

    def run_execution_loop(self):
        """
        Background listener loop: reads live_market_data.json ticks every second
        to process real-time updates and trigger strategy evaluations.
        """
        self.establish_orb_ranges()
        
        last_audit = 0.0
        self.log_message("Execution monitor loop started successfully.")
        
        while True:
            try:
                # 1. Perform audit/reconciliation every 15 seconds
                now = time.time()
                if now - last_audit > 15.0:
                    self.audit_active_positions_with_broker()
                    last_audit = now
                    
                # 2. Reload active trades from disk to synchronize with remote entries (Telegram / Dashboard)
                self.load_active_trades()
                
                # 3. Read live data cache from logger updates
                if os.path.exists(LIVE_MARKET_DATA_FILE):
                    with open(LIVE_MARKET_DATA_FILE, "r") as f:
                        market_snapshot = json.load(f)
                        
                    for sym in NIFTY_50_TICKERS:
                        ticker_data = market_snapshot.get(sym)
                        if not ticker_data:
                            continue
                            
                        ltp = ticker_data.get("ltp")
                        if ltp is None:
                            continue
                            
                        # Update price status for held positions
                        if sym in self.active_trades:
                            self.process_live_price_update(sym, ltp, ticker_data)
                        else:
                            # Evaluate breakout triggers on inactive scanners
                            self.evaluate_strategy_signals(sym, ltp, ticker_data)
                            
            except Exception as e:
                self.log_message(f"Exception inside execution loop: {e}", is_error=True)
                
            time.sleep(1.0) # Tick processing resolution frequency


# -------------------------------------------------------------
# MAIN RUNNER SCRIPT ENTRY
# -------------------------------------------------------------
if __name__ == "__main__":
    import sys
    # Boot default dry-run mode simulator for safety verification unless 'live' is specified
    is_dry = True
    if len(sys.argv) > 1 and sys.argv[1].lower() == "live":
        is_dry = False
    engine = KiteExecutionCore(dry_run=is_dry)
    engine.run_execution_loop()
