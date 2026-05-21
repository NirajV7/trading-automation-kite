import os
import json
import time
from datetime import datetime, timedelta, date
import threading
from collections import deque
import pandas as pd

# pyrefly: ignore [missing-import]
from kiteconnect import KiteConnect, KiteTicker

from config import (
    KITE_API_KEY,
    KITE_API_SECRET,
    KITE_TOKEN_FILE,
    NIFTY_50_TICKERS,
    TICKER_LOG,
    ENGINE_LOG
)
from kite_auth_manager import get_kite_client
from kite_utils import round_to_tick, handle_auth_failure

# File to store mapping of symbol -> instrument token
INSTRUMENT_MAPPING_FILE = os.path.join(
    os.path.dirname(KITE_TOKEN_FILE), "instrument_mappings.json"
)
LIVE_MARKET_DATA_FILE = os.path.join(
    os.path.dirname(KITE_TOKEN_FILE), "live_market_data.json"
)

class TechnicalIndicators:
    """Calculates all math/technical indicators for candles."""

    @staticmethod
    def calculate_ema(closes, period):
        """Calculates Exponential Moving Average (EMA)."""
        if len(closes) < period:
            return [None] * len(closes)
        
        ema = [None] * len(closes)
        sma = sum(closes[:period]) / period
        ema[period - 1] = sma
        
        alpha = 2.0 / (period + 1)
        for i in range(period, len(closes)):
            prev = ema[i - 1]
            if prev is None:
                prev = sma
            ema[i] = (closes[i] * alpha) + (prev * (1.0 - alpha))
        return ema

    @staticmethod
    def calculate_rsi(closes, period=14):
        """Calculates Wilder's Relative Strength Index (RSI)."""
        if len(closes) <= period:
            return [None] * len(closes)
            
        rsi_values = [None] * len(closes)
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(0.0, diff))
            losses.append(max(0.0, -diff))
            
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        if avg_loss == 0:
            rs = 99999.0
        else:
            rs = avg_gain / avg_loss
        rsi_values[period] = 100.0 - (100.0 / (1.0 + rs))
        
        for i in range(period + 1, len(closes)):
            gain = gains[i - 1]
            loss = losses[i - 1]
            avg_gain = ((avg_gain * (period - 1)) + gain) / period
            avg_loss = ((avg_loss * (period - 1)) + loss) / period
            
            if avg_loss == 0:
                rsi_values[i] = 100.0 if avg_gain > 0 else 50.0
            else:
                rs = avg_gain / avg_loss
                rsi_values[i] = 100.0 - (100.0 / (1.0 + rs))
                
        return rsi_values

    @staticmethod
    def calculate_vwap(candles):
        """
        Calculates Volume Weighted Average Price (VWAP) resetting daily.
        candles is a list of dictionaries containing date, high, low, close, volume keys.
        """
        vwap = [None] * len(candles)
        current_day = None
        cum_pv = 0.0
        cum_vol = 0.0
        
        for i, c in enumerate(candles):
            dt = c["date"]
            day_str = dt.strftime("%Y-%m-%d") if isinstance(dt, datetime) else str(dt)[:10]
            
            if day_str != current_day:
                current_day = day_str
                cum_pv = 0.0
                cum_vol = 0.0
                
            typical_price = (c["high"] + c["low"] + c["close"]) / 3.0
            cum_pv += typical_price * c["volume"]
            cum_vol += c["volume"]
            
            if cum_vol > 0:
                vwap[i] = cum_pv / cum_vol
            else:
                vwap[i] = typical_price
                
        return vwap

    @staticmethod
    def calculate_adr(daily_candles, period=14):
        """Calculates 14-period Average Daily Range (percentage & absolute)."""
        if not daily_candles:
            return 0.0, 0.0
        
        # Take up to the last 'period' completed daily candles
        valid_candles = daily_candles[-period:]
        pct_ranges = []
        abs_ranges = []
        
        for c in valid_candles:
            h = c["high"]
            l = c["low"]
            if l > 0:
                pct_ranges.append(((h - l) / l) * 100.0)
                abs_ranges.append(h - l)
                
        if not pct_ranges:
            return 0.0, 0.0
            
        adr_pct = sum(pct_ranges) / len(pct_ranges)
        adr_abs = sum(abs_ranges) / len(abs_ranges)
        return adr_pct, adr_abs


class KiteDataLogger:
    """Manages historical bootstrapper, live tick collection, and indicator calculations."""

    def __init__(self):
        self.lock = threading.Lock()
        self.kite = None
        self.kws = None
        
        # Mappings
        self.symbol_to_token = {}
        self.token_to_symbol = {}
        
        # Historical & live deques (capped to 300 to prevent memory growth)
        self.candles_1m = {sym: deque(maxlen=300) for sym in NIFTY_50_TICKERS}
        self.candles_5m = {sym: deque(maxlen=300) for sym in NIFTY_50_TICKERS}
        self.candles_15m = {sym: deque(maxlen=300) for sym in NIFTY_50_TICKERS}
        self.candles_day = {sym: deque(maxlen=50) for sym in NIFTY_50_TICKERS}
        
        # Current active open candles
        # {symbol: {open, high, low, close, volume, start_volume_traded, date}}
        self.active_1m = {}
        self.active_5m = {}
        self.active_15m = {}
        
        # Cached ADR values (since they are calculated from daily candles on startup)
        self.adr_cache = {sym: {"pct": 0.0, "abs": 0.0} for sym in NIFTY_50_TICKERS}
        
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
                    
            # Map Nifty 50
            for sym in NIFTY_50_TICKERS:
                if sym in temp_sym_to_tok:
                    self.symbol_to_token[sym] = temp_sym_to_tok[sym]
                    self.token_to_symbol[temp_sym_to_tok[sym]] = sym
                else:
                    self.log_message(f"Warning: ticker {sym} not found in Zerodha instruments list.", is_error=True)
            
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

        for idx, sym in enumerate(NIFTY_50_TICKERS):
            token = self.symbol_to_token.get(sym)
            if not token:
                continue
                
            self.log_message(f"Bootstrapping historical candles for {sym} ({idx+1}/{len(NIFTY_50_TICKERS)})...")
            
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

            # Populate latest indicators in live_state
            if sym not in self.live_state:
                self.live_state[sym] = {}
                
            self.live_state[sym].update({
                "symbol": sym,
                "adr_percentage": round(self.adr_cache[sym]["pct"], 2),
                "adr_absolute": round(self.adr_cache[sym]["abs"], 2),
                
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
            self.live_state[sym].update({
                "ltp": ltp,
                "change": round(pct_change, 2),
                "volume": vol_traded,
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
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    def write_live_state_to_file(self):
        """Periodically flushes live technical state atomically to data/live_market_data.json."""
        while True:
            time.sleep(1.0) # Flush every 1 second
            try:
                with self.lock:
                    snapshot = dict(self.live_state)
                    
                if not snapshot:
                    continue
                    
                # Atomic file writing
                temp_fd, temp_path = tempfile_mkstemp(dir=os.path.dirname(LIVE_MARKET_DATA_FILE))
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(snapshot, f, indent=4)
                os.replace(temp_path, LIVE_MARKET_DATA_FILE)
            except Exception as e:
                # inline import helper to prevent circular dependency
                pass

def tempfile_mkstemp(dir):
    import tempfile
    return tempfile.mkstemp(dir=dir)

def run_data_logger():
    """Main execution block to launch the data logger."""
    logger = KiteDataLogger()
    logger.log_message("Initializing Zerodha Kite Data Logger engine...")
    
    if not logger.initialize_kite():
        logger.log_message("Failed to initialize Kite client. Exiting.", is_error=True)
        return
        
    logger.load_or_fetch_instrument_tokens()
    logger.bootstrap_historical_data()
    
    # Start periodic file writer thread
    threading.Thread(target=logger.write_live_state_to_file, daemon=True).start()
    
    # Read access token and API Key for Ticker
    try:
        with open(KITE_TOKEN_FILE, "r") as f:
            token_data = json.load(f)
            access_token = token_data["access_token"]
    except Exception as e:
        logger.log_message(f"Failed to read cached access token: {e}", is_error=True)
        return
        
    # Setup KiteTicker WebSocket
    kws = KiteTicker(api_key=KITE_API_KEY, access_token=access_token)
    logger.kws = kws
    
    def on_ticks(ws, ticks):
        for tick in ticks:
            logger.process_tick(tick)
            
        # Log raw tick summaries to ticker.log
        try:
            with open(TICKER_LOG, "a") as f:
                for tick in ticks:
                    token = tick.get("instrument_token")
                    sym = logger.token_to_symbol.get(token, f"UNKNOWN_{token}")
                    f.write(f"{datetime.now().isoformat()} | {sym} | LTP: {tick.get('last_price')} | Vol: {tick.get('volume_traded')}\n")
        except Exception:
            pass

    def on_connect(ws, response):
        logger.log_message("Kite WebSocket connected! Subscribing to Nifty 50 tokens...")
        tokens = list(logger.symbol_to_token.values())
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_FULL, tokens)
        logger.log_message(f"Subscribed to {len(tokens)} tokens in FULL mode.")

    def on_close(ws, code, reason):
        logger.log_message(f"Kite WebSocket connection closed: Code={code}, Reason={reason}")

    def on_error(ws, code, reason):
        logger.log_message(f"Kite WebSocket error occurred: Code={code}, Reason={reason}", is_error=True)

    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close
    kws.on_error = on_error
    
    # Start loop in background thread to run until manually stopped
    logger.log_message("Starting KiteTicker WebSocket loop...")
    kws.connect()

if __name__ == "__main__":
    run_data_logger()
