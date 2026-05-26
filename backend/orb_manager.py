import time
from datetime import datetime, time as datetime_time
from config import NIFTY_50_TICKERS
from kite_auth_manager import get_kite_client
from kite_utils import handle_auth_failure

class ORBManagerMixin:
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
