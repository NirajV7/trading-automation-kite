import os
import json
import time
from datetime import datetime, timedelta
import threading
from collections import deque

from config import (
    NIFTY_50_TICKERS,
    ENGINE_LOG,
    INSTRUMENT_MAPPING_FILE,
    LIVE_MARKET_DATA_FILE
)
from kite_auth_manager import get_kite_client
from kite_utils import handle_auth_failure
from kite_indicators import TechnicalIndicators


class KiteDataLogger:
    """Manages historical bootstrapper, live tick collection, and indicator calculations."""

    def __init__(self):
        self.lock = threading.Lock()
        self.kite = None
        self.kws = None
        
        # Mappings
        self.symbol_to_token = {}
        self.token_to_symbol = {}
        
        # Get watchlist symbols at boot
        watchlist_symbols = self.get_current_watchlist_symbols()
        all_initial_symbols = list(set(NIFTY_50_TICKERS) | watchlist_symbols)
        
        # Historical & live deques (capped to 300 to prevent memory growth)
        self.candles_1m = {sym: deque(maxlen=300) for sym in all_initial_symbols}
        self.candles_5m = {sym: deque(maxlen=300) for sym in all_initial_symbols}
        self.candles_15m = {sym: deque(maxlen=300) for sym in all_initial_symbols}
        self.candles_day = {sym: deque(maxlen=50) for sym in all_initial_symbols}
        
        # Current active open candles
        # {symbol: {open, high, low, close, volume, start_volume_traded, date}}
        self.active_1m = {}
        self.active_5m = {}
        self.active_15m = {}
        
        # Cached ADR values (since they are calculated from daily candles on startup)
        self.adr_cache = {sym: {"pct": 0.0, "abs": 0.0} for sym in all_initial_symbols}
        
        # Latest live state for the frontend / execution core
        # {symbol: {ltp, vwap, ema20_5m, rsi_5m, ...}}
        self.live_state = {}

    def log_message(self, message, is_error=False):
        """Appends logs to engine.log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = "[ERROR]" if is_error else "[INFO]"
        log_line = f"{timestamp} {prefix} {message}\n"
        print(f"{prefix} {message}")
        try:
            with open(ENGINE_LOG, "a") as f:
                f.write(log_line)
        except Exception as e:
            print(f"Failed to write log to file: {e}")

    def initialize_kite(self):
        """Fetches the authenticated Kite client."""
        try:
            self.kite = get_kite_client()
            self.log_message("Kite Connect client initialized successfully.")
            return True
        except Exception as e:
            self.log_message(f"Failed to initialize Kite client: {e}", is_error=True)
            return False

    def load_or_fetch_instrument_tokens(self):
        """Resolves instrument tokens for NIFTY 50 tickers and caches them."""
        # 1. Try reading from cached JSON file
        if os.path.exists(INSTRUMENT_MAPPING_FILE):
            try:
                with open(INSTRUMENT_MAPPING_FILE, "r") as f:
                    mappings = json.load(f)
                    self.symbol_to_token = {k: int(v) for k, v in mappings.get("symbol_to_token", {}).items()}
                    self.token_to_symbol = {int(k): v for k, v in mappings.get("token_to_symbol", {}).items()}
                # Ensure all Nifty 50 tickers are covered in the cache
                missing_any = any(sym not in self.symbol_to_token for sym in NIFTY_50_TICKERS)
                if not missing_any:
                    self.log_message("Loaded instrument mappings from cache successfully.")
                    return
            except Exception as e:
                self.log_message(f"Error reading instrument mapping cache: {e}", is_error=True)

        # 2. Fetch from Zerodha if cache is invalid or missing symbols
        self.log_message("Fetching full NSE instruments list from Zerodha...")
        try:
            instruments = self.kite.instruments("NSE")
            temp_sym_to_tok = {}
            temp_tok_to_sym = {}
            
            for inst in instruments:
                symbol = inst.get("tradingsymbol")
                token = inst.get("instrument_token")
                if symbol and token:
                    temp_sym_to_tok[symbol] = int(token)
                    temp_tok_to_sym[int(token)] = symbol
                    
            # Save all instruments to cache
            self.symbol_to_token = temp_sym_to_tok
            self.token_to_symbol = temp_tok_to_sym
            
            # Save mappings to cache file
            with open(INSTRUMENT_MAPPING_FILE, "w") as f:
                json.dump({
                    "symbol_to_token": self.symbol_to_token,
                    "token_to_symbol": {str(k): v for k, v in self.token_to_symbol.items()}
                }, f, indent=4)
            self.log_message("Instrument mappings cached successfully.")
        except Exception as e:
            self.log_message(f"Failed to fetch instruments from Zerodha: {e}", is_error=True)
            handle_auth_failure(e)

    def bootstrap_historical_data(self):
        """Fetches historical candles on boot to initialize indicators."""
        self.log_message("Starting historical data bootstrapping...")
        
        today = datetime.now()
        
        # Calculate dates
        day_from = today - timedelta(days=50) # 50 calendar days for daily candles
        m5_from = today - timedelta(days=8)   # 8 calendar days for 5m candles (~600 bars)
        m15_from = today - timedelta(days=20) # 20 calendar days for 15m candles (~500 bars)
        m1_from = today - timedelta(days=3)   # 3 calendar days for 1m candles (~1125 bars)

        active_bootstrap_symbols = list(set(NIFTY_50_TICKERS) | self.get_current_watchlist_symbols())
        for idx, sym in enumerate(active_bootstrap_symbols):
            token = self.symbol_to_token.get(sym)
            if not token:
                continue
                
            self.log_message(f"Bootstrapping historical candles for {sym} ({idx+1}/{len(active_bootstrap_symbols)})...")
            
            # Daily candles for ADR calculation
            try:
                daily_data = self.kite.historical_data(
                    instrument_token=token,
                    from_date=day_from.date(),
                    to_date=today.date(),
                    interval="day"
                )
                self.candles_day[sym].extend(daily_data)
                adr_pct, adr_abs = TechnicalIndicators.calculate_adr(list(self.candles_day[sym]))
                self.adr_cache[sym] = {"pct": adr_pct, "abs": adr_abs}
            except Exception as e:
                self.log_message(f"Failed fetching daily candles for {sym}: {e}", is_error=True)

            # 1-minute candles
            try:
                m1_data = self.kite.historical_data(
                    instrument_token=token,
                    from_date=m1_from,
                    to_date=today,
                    interval="minute"
                )
                self.candles_1m[sym].extend(m1_data)
            except Exception as e:
                self.log_message(f"Failed fetching 1m candles for {sym}: {e}", is_error=True)

            # 5-minute candles
            try:
                m5_data = self.kite.historical_data(
                    instrument_token=token,
                    from_date=m5_from,
                    to_date=today,
                    interval="5minute"
                )
                self.candles_5m[sym].extend(m5_data)
            except Exception as e:
                self.log_message(f"Failed fetching 5m candles for {sym}: {e}", is_error=True)

            # 15-minute candles
            try:
                m15_data = self.kite.historical_data(
                    instrument_token=token,
                    from_date=m15_from,
                    to_date=today,
                    interval="15minute"
                )
                self.candles_15m[sym].extend(m15_data)
            except Exception as e:
                self.log_message(f"Failed fetching 15m candles for {sym}: {e}", is_error=True)

            # Pre-compute indicators for bootstrapped historical series
            self.recalculate_all_indicators_for_symbol(sym)
            
            # Sleep briefly to respect rate limits (3 historical calls per stock, 50 stocks = 150 calls)
            time.sleep(0.05)

        self.log_message("Bootstrapping complete! All indicator queues pre-populated.")

    def recalculate_all_indicators_for_symbol(self, sym):
        """Computes technical indicator arrays for a symbol and stores latest values."""
        with self.lock:
            # 1m
            c1m = list(self.candles_1m[sym])
            closes_1m = [c["close"] for c in c1m]
            ema20_1m = TechnicalIndicators.calculate_ema(closes_1m, 20)
            ema50_1m = TechnicalIndicators.calculate_ema(closes_1m, 50)
            ema200_1m = TechnicalIndicators.calculate_ema(closes_1m, 200)
            vwap_1m = TechnicalIndicators.calculate_vwap(c1m)
            rsi_1m = TechnicalIndicators.calculate_rsi(closes_1m, 14)

            # 5m
            c5m = list(self.candles_5m[sym])
            closes_5m = [c["close"] for c in c5m]
            ema20_5m = TechnicalIndicators.calculate_ema(closes_5m, 20)
            ema50_5m = TechnicalIndicators.calculate_ema(closes_5m, 50)
            ema200_5m = TechnicalIndicators.calculate_ema(closes_5m, 200)
            vwap_5m = TechnicalIndicators.calculate_vwap(c5m)
            rsi_5m = TechnicalIndicators.calculate_rsi(closes_5m, 14)

            # 15m
            c15m = list(self.candles_15m[sym])
            closes_15m = [c["close"] for c in c15m]
            ema20_15m = TechnicalIndicators.calculate_ema(closes_15m, 20)
            ema50_15m = TechnicalIndicators.calculate_ema(closes_15m, 50)
            ema200_15m = TechnicalIndicators.calculate_ema(closes_15m, 200)
            vwap_15m = TechnicalIndicators.calculate_vwap(c15m)
            rsi_15m = TechnicalIndicators.calculate_rsi(closes_15m, 14)

            # Volume baseline calculations (average volume of the last 20 closed candles)
            volumes_15m = [c["volume"] for c in c15m[-20:]]
            avg_vol_15m = sum(volumes_15m) / len(volumes_15m) if volumes_15m else 0.0
            
            volumes_5m = [c["volume"] for c in c5m[-20:]]
            avg_vol_5m = sum(volumes_5m) / len(volumes_5m) if volumes_5m else 0.0

            volumes_1m = [c["volume"] for c in c1m[-20:]]
            avg_vol_1m = sum(volumes_1m) / len(volumes_1m) if volumes_1m else 0.0

            # Safe string format for last closed 5m timestamp
            last_closed_5m = c5m[-1]["date"] if c5m else None
            if last_closed_5m:
                if hasattr(last_closed_5m, "strftime"):
                    last_closed_5m_str = last_closed_5m.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    last_closed_5m_str = str(last_closed_5m)
            else:
                last_closed_5m_str = None

            # Populate latest indicators in live_state
            if sym not in self.live_state:
                self.live_state[sym] = {}
                
            self.live_state[sym].update({
                "symbol": sym,
                "adr_percentage": round(self.adr_cache[sym]["pct"], 2),
                "adr_absolute": round(self.adr_cache[sym]["abs"], 2),
                "avg_vol_15m": avg_vol_15m,
                "avg_vol_5m": avg_vol_5m,
                "avg_vol_1m": avg_vol_1m,
                
                # 1m closed candle stats
                "prev_open_1m": c1m[-1]["open"] if c1m else None,
                "prev_close_1m": c1m[-1]["close"] if c1m else None,
                "prev_high_1m": c1m[-1]["high"] if c1m else None,
                "prev_low_1m": c1m[-1]["low"] if c1m else None,
                "prev_volume_1m": c1m[-1]["volume"] if c1m else None,

                # 5m closed candle stats
                "prev_high_5m": c5m[-1]["high"] if c5m else None,
                "prev_low_5m": c5m[-1]["low"] if c5m else None,
                "prev_close_5m": c5m[-1]["close"] if c5m else None,
                "prev_volume_5m": c5m[-1]["volume"] if c5m else None,
                "last_closed_5m_time": last_closed_5m_str,
                
                # 1m
                "ema20_1m": ema20_1m[-1] if ema20_1m else None,
                "ema50_1m": ema50_1m[-1] if ema50_1m else None,
                "ema200_1m": ema200_1m[-1] if ema200_1m else None,
                "vwap_1m": vwap_1m[-1] if vwap_1m else None,
                "rsi_1m": rsi_1m[-1] if rsi_1m else None,

                # 5m
                "ema20_5m": ema20_5m[-1] if ema20_5m else None,
                "ema50_5m": ema50_5m[-1] if ema50_5m else None,
                "ema200_5m": ema200_5m[-1] if ema200_5m else None,
                "vwap_5m": vwap_5m[-1] if vwap_5m else None,
                "rsi_5m": rsi_5m[-1] if rsi_5m else None,

                # 15m
                "ema20_15m": ema20_15m[-1] if ema20_15m else None,
                "ema50_15m": ema50_15m[-1] if ema50_15m else None,
                "ema200_15m": ema200_15m[-1] if ema200_15m else None,
                "vwap_15m": vwap_15m[-1] if vwap_15m else None,
                "rsi_15m": rsi_15m[-1] if rsi_15m else None,
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    def process_tick(self, tick):
        """Processes a single incoming ticker quote and aggregates candles."""
        token = tick.get("instrument_token")
        sym = self.token_to_symbol.get(token)
        if not sym:
            return
            
        # Ignore tick if symbol is not initialized (prevent KeyError during dynamic addition bootstrapping)
        if sym not in self.candles_1m:
            return
            
        ltp = tick.get("last_price")
        vol_traded = tick.get("volume_traded")
        
        if ltp is None or vol_traded is None:
            return
            
        # Get timestamp. Fallback to system time if exchange time is None
        tick_time = tick.get("exchange_timestamp") or datetime.now()
        
        # Calculate percent change from previous close (ohlc.close)
        ohlc = tick.get("ohlc", {})
        prev_close = ohlc.get("close")
        pct_change = 0.0
        if prev_close and prev_close > 0:
            pct_change = ((ltp - prev_close) / prev_close) * 100.0

        with self.lock:
            # Update immediate live details
            if sym not in self.live_state:
                self.live_state[sym] = {"symbol": sym}
            
            # Extract daily ohlc and volume metrics from tick
            today_open = ohlc.get("open")
            today_high = ohlc.get("high")
            today_low = ohlc.get("low")
            
            self.live_state[sym].update({
                "ltp": ltp,
                "change": round(pct_change, 2),
                "volume": vol_traded,
                "today_open": today_open if today_open else self.live_state[sym].get("today_open"),
                "today_high": today_high if today_high else self.live_state[sym].get("today_high"),
                "today_low": today_low if today_low else self.live_state[sym].get("today_low"),
                "buy_quantity": tick.get("total_buy_quantity", tick.get("buy_quantity", 0.0)),
                "sell_quantity": tick.get("total_sell_quantity", tick.get("sell_quantity", 0.0))
            })
            
            # Aggregate candles for 1m, 5m, and 15m
            self.aggregate_candle_for_interval(sym, ltp, vol_traded, tick_time, 1, self.active_1m, self.candles_1m)
            self.aggregate_candle_for_interval(sym, ltp, vol_traded, tick_time, 5, self.active_5m, self.candles_5m)
            self.aggregate_candle_for_interval(sym, ltp, vol_traded, tick_time, 15, self.active_15m, self.candles_15m)

    def aggregate_candle_for_interval(self, sym, ltp, vol_traded, tick_time, interval_minutes, active_dict, candles_dict):
        """Handles closing and opening new candles for a specific interval."""
        # Align timestamp to timeframe floor
        minute_floor = (tick_time.minute // interval_minutes) * interval_minutes
        candle_start = tick_time.replace(minute=minute_floor, second=0, microsecond=0)
        
        active = active_dict.get(sym)
        
        if not active:
            # First tick for this interval
            active_dict[sym] = {
                "date": candle_start,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": 0,
                "start_volume_traded": vol_traded
            }
            return

        # Check if we moved to a new timeframe block
        if candle_start > active["date"]:
            # Close active candle
            closed_candle = {
                "date": active["date"],
                "open": active["open"],
                "high": active["high"],
                "low": active["low"],
                "close": active["close"],
                "volume": max(0, vol_traded - active["start_volume_traded"])
            }
            
            # Append closed candle to the queue
            candles_dict[sym].append(closed_candle)
            
            # Initialize a new active candle
            active_dict[sym] = {
                "date": candle_start,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": 0,
                "start_volume_traded": vol_traded
            }
            
            # Trigger indicators update in a background thread to prevent blocking tick processing
            threading.Thread(target=self.recalculate_all_indicators_for_symbol, args=(sym,), daemon=True).start()
            
        else:
            # Update active candle boundaries
            active["high"] = max(active["high"], ltp)
            active["low"] = min(active["low"], ltp)
            active["close"] = ltp
            active["volume"] = max(0, vol_traded - active["start_volume_traded"])
            
            # Real-time indicators evaluation:
            # Feed current closes (including active close) to calculate real-time EMA/RSI/VWAP
            closed_list = list(candles_dict[sym])
            temp_candle = {
                "date": active["date"],
                "open": active["open"],
                "high": active["high"],
                "low": active["low"],
                "close": active["close"],
                "volume": active["volume"]
            }
            full_series = closed_list + [temp_candle]
            closes = [c["close"] for c in full_series]
            
            # Calculate real-time indicators for current active candle
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)[-1]
            ema50 = TechnicalIndicators.calculate_ema(closes, 50)[-1]
            ema200 = TechnicalIndicators.calculate_ema(closes, 200)[-1]
            vwap = TechnicalIndicators.calculate_vwap(full_series)[-1]
            rsi = TechnicalIndicators.calculate_rsi(closes, 14)[-1]
            
            # Update live state instantly
            pfx = f"_{interval_minutes}m"
            self.live_state[sym].update({
                f"ema20{pfx}": ema20,
                f"ema50{pfx}": ema50,
                f"ema200{pfx}": ema200,
                f"vwap{pfx}": vwap,
                f"rsi{pfx}": rsi,
                f"active_vol{pfx}": active["volume"],
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    def write_live_state_to_file(self):
        """Periodically flushes live technical state atomically to data/live_market_data.json."""
        import tempfile
        while True:
            time.sleep(1.0) # Flush every 1 second
            try:
                with self.lock:
                    snapshot = dict(self.live_state)
                    
                if not snapshot:
                    continue
                    
                # Atomic file writing
                temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(LIVE_MARKET_DATA_FILE))
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(snapshot, f, indent=4)
                os.replace(temp_path, LIVE_MARKET_DATA_FILE)
            except Exception as e:
                pass

    def get_current_watchlist_symbols(self):
        """Loads and returns a set of cleaned symbols from data/watchlist.json."""
        from config import WATCHLIST_FILE
        if not os.path.exists(WATCHLIST_FILE):
            return set()
        try:
            with open(WATCHLIST_FILE, "r") as f:
                wl = json.load(f)
            def clean_sym(s):
                return s.replace("NSE:", "").replace("-EQ", "").replace("-BE", "").upper()
            return set(clean_sym(s) for s in wl.get("buy", []) + wl.get("sell", []))
        except Exception:
            return set()

    def start_watchlist_monitor(self):
        """Starts a background thread to dynamically watch and subscribe to watchlist changes."""
        threading.Thread(target=self.watchlist_monitor_loop, daemon=True).start()

    def watchlist_monitor_loop(self):
        """Monitors data/watchlist.json every 5 seconds for new additions."""
        time.sleep(10.0) # wait briefly for startup boot to settle
        self.log_message("Watchlist monitor thread started successfully.")
        
        # Track symbols already bootstrapped
        tracked_symbols = set(NIFTY_50_TICKERS) | self.get_current_watchlist_symbols()
        
        while True:
            time.sleep(5.0)
            try:
                current_wl = self.get_current_watchlist_symbols()
                new_symbols = current_wl - tracked_symbols
                
                if new_symbols:
                    self.log_message(f"Watchlist monitor: Detected new symbols to subscribe: {list(new_symbols)}")
                    for sym in new_symbols:
                        token = self.symbol_to_token.get(sym)
                        if not token:
                            self.log_message(f"Watchlist: Symbol {sym} not found in token cache. Refreshing instruments...")
                            self.load_or_fetch_instrument_tokens()
                            token = self.symbol_to_token.get(sym)
                            
                        if token:
                            self.log_message(f"Watchlist: Bootstrapping indicators for {sym} (Token: {token})...")
                            self.bootstrap_single_symbol(sym, token)
                            
                            # Subscribe WebSocket if connected
                            if self.kws:
                                self.kws.subscribe([token])
                                self.kws.set_mode(self.kws.MODE_FULL, [token])
                                self.log_message(f"Watchlist: Successfully subscribed WebSocket to {sym} (Token: {token})")
                            
                            tracked_symbols.add(sym)
                        else:
                            self.log_message(f"Watchlist error: Symbol {sym} could not be resolved. Skipping.", is_error=True)
            except Exception as e:
                self.log_message(f"Exception in watchlist monitor loop: {e}", is_error=True)

    def bootstrap_single_symbol(self, sym, token):
        """Fetches historical candles for a single symbol to initialize indicators."""
        from datetime import timedelta
        
        # Initialize deques in memory
        self.candles_1m[sym] = deque(maxlen=300)
        self.candles_5m[sym] = deque(maxlen=300)
        self.candles_15m[sym] = deque(maxlen=300)
        self.candles_day[sym] = deque(maxlen=50)
        self.adr_cache[sym] = {"pct": 0.0, "abs": 0.0}
        
        today = datetime.now()
        day_from = today - timedelta(days=50)
        m5_from = today - timedelta(days=8)
        m15_from = today - timedelta(days=20)
        m1_from = today - timedelta(days=3)

        # 1. Daily for ADR
        try:
            daily_data = self.kite.historical_data(
                instrument_token=token,
                from_date=day_from.date(),
                to_date=today.date(),
                interval="day"
            )
            self.candles_day[sym].extend(daily_data)
            adr_pct, adr_abs = TechnicalIndicators.calculate_adr(list(self.candles_day[sym]))
            self.adr_cache[sym] = {"pct": adr_pct, "abs": adr_abs}
        except Exception as e:
            self.log_message(f"Failed fetching daily candles for {sym}: {e}", is_error=True)

        # 2. 1m
        try:
            m1_data = self.kite.historical_data(
                instrument_token=token,
                from_date=m1_from,
                to_date=today,
                interval="minute"
            )
            self.candles_1m[sym].extend(m1_data)
        except Exception as e:
            self.log_message(f"Failed fetching 1m candles for {sym}: {e}", is_error=True)

        # 3. 5m
        try:
            m5_data = self.kite.historical_data(
                instrument_token=token,
                from_date=m5_from,
                to_date=today,
                interval="5minute"
            )
            self.candles_5m[sym].extend(m5_data)
        except Exception as e:
            self.log_message(f"Failed fetching 5m candles for {sym}: {e}", is_error=True)

        # 4. 15m
        try:
            m15_data = self.kite.historical_data(
                instrument_token=token,
                from_date=m15_from,
                to_date=today,
                interval="15minute"
            )
            self.candles_15m[sym].extend(m15_data)
        except Exception as e:
            self.log_message(f"Failed fetching 15m candles for {sym}: {e}", is_error=True)
            
        # Recalculate indicators once
        self.recalculate_all_indicators_for_symbol(sym)
