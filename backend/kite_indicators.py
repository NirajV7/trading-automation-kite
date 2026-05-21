from datetime import datetime

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
