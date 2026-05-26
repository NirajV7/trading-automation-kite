import json
from datetime import datetime
import threading
from kiteconnect import KiteTicker

from config import (
    KITE_API_KEY,
    KITE_TOKEN_FILE,
    TICKER_LOG
)
from kite_data_logger import KiteDataLogger

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
    
    # Start watchlist monitor background thread
    logger.start_watchlist_monitor()
    
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
        from config import NIFTY_50_TICKERS
        logger.log_message("Kite WebSocket connected! Resolving initial subscription tokens...")
        
        # Subscribe to Nifty 50
        tokens = [logger.symbol_to_token[s] for s in NIFTY_50_TICKERS if s in logger.symbol_to_token]
        # Also subscribe to active watchlist symbols at boot
        wl_symbols = logger.get_current_watchlist_symbols()
        for sym in wl_symbols:
            if sym in logger.symbol_to_token:
                tok = logger.symbol_to_token[sym]
                if tok not in tokens:
                    tokens.append(tok)
                    
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
