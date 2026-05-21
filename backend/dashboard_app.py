import os
import json
import subprocess
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import workspace configuration & managers
import config
from kite_auth_manager import check_kite_auth, exchange_kite_token
from kite_telemetry import get_kite_margin, get_kite_orders, get_kite_positions
from kite_order_manager import panic_square_off, exit_single_position, book_half_position, modify_or_place_sl
from kite_utils import get_public_ip

# Initialize FastAPI App
app = FastAPI(title="Kite Quant Terminal API Backend", version="1.0.0")

# Enable CORS for frontend integration (Electron app or web interface)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------------
def is_process_running(script_name: str) -> bool:
    """
    Checks if a Python process with the given script name is running.
    Uses pgrep to locate the process identifier.
    """
    try:
        cmd = f"pgrep -f '{script_name}'"
        subprocess.check_output(cmd, shell=True)
        return True
    except subprocess.CalledProcessError:
        return False

def get_python_executable():
    """
    Returns the path to the workspace venv Python interpreter.
    """
    return os.path.join(config.BACKEND_DIR, "venv", "bin", "python")

def load_watchlist():
    """
    Reads the watchlist JSON file. If it doesn't exist, initializes it.
    """
    if not os.path.exists(config.WATCHLIST_FILE):
        watchlist = {"buy": [], "sell": []}
        try:
            with open(config.WATCHLIST_FILE, "w") as f:
                json.dump(watchlist, f, indent=4)
        except Exception as e:
            print(f"Error creating watchlist file: {e}")
        return watchlist
    try:
        with open(config.WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading watchlist: {e}")
        return {"buy": [], "sell": []}


# -------------------------------------------------------------
# SYSTEM & CORE PROCESS CONTROLS
# -------------------------------------------------------------
@app.get("/api/status")
def api_status():
    """
    System status endpoint reporting connection and process states.
    Checks:
    - Data Logger status (KiteTicker WebSocket)
    - Execution Core status (Simulated or Live engine)
    - Zerodha Kite Auth status & margin balances
    - IP whitelist status for remote Tailscale validation
    """
    logger_running = is_process_running("run_data_logger.py")
    
    # Check if execution core is running
    engine_state = "stopped"
    if is_process_running("kite_execution_core.py"):
        # We look at process args to distinguish live vs dry-run
        # Check if "live" string is present in process arguments
        try:
            pgrep_output = subprocess.check_output("ps aux | grep kite_execution_core.py | grep -v grep", shell=True).decode()
            if "live" in pgrep_output.lower():
                engine_state = "live"
            else:
                engine_state = "dry"
        except Exception:
            engine_state = "dry"

    # Zerodha Auth checks
    needs_login, auth_url = check_kite_auth()
    margin_data = None
    if not needs_login:
        margin_data = get_kite_margin()

    # Network / Tailscale Check
    network_info = get_public_ip()

    return JSONResponse({
        "status": "success",
        "data_logger": "active" if logger_running else "stopped",
        "kite_engine": engine_state,
        "kite_needs_login": needs_login,
        "kite_auth_url": auth_url,
        "kite_margin": margin_data,
        "network": network_info
    })

@app.get("/api/logs")
def api_logs():
    """
    Returns the last 30 lines of the shared system engine log.
    Automatically rotates/clears the log file if it exceeds 1MB.
    """
    if not os.path.exists(config.ENGINE_LOG):
        return JSONResponse({"logs": "Log file not found."})
        
    try:
        # Check file size for automatic rotation
        if os.path.getsize(config.ENGINE_LOG) > 1024 * 1024:
            with open(config.ENGINE_LOG, "w") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] ♻️ Engine Log Rotated (Exceeded 1MB)\n")
        
        with open(config.ENGINE_LOG, "r") as f:
            lines = f.readlines()
            last_lines = "".join(lines[-30:])
            return JSONResponse({"logs": last_lines})
    except Exception as e:
        return JSONResponse({"logs": f"Error reading logs: {str(e)}"})

@app.post("/api/system/start_logger")
def start_logger():
    """
    Launches the Zerodha Kite Data Logger process in the background.
    """
    if is_process_running("run_data_logger.py"):
        return JSONResponse({"status": "error", "message": "Data Logger is already running."})
        
    venv_py = get_python_executable()
    script_path = os.path.join(config.BACKEND_DIR, "run_data_logger.py")
    
    with open(config.ENGINE_LOG, "a") as log_file:
        subprocess.Popen(
            [venv_py, "-u", script_path],
            cwd=config.BACKEND_DIR,
            stdout=log_file,
            stderr=log_file
        )
    return JSONResponse({"status": "success", "message": "Kite Data Logger engine started."})

@app.post("/api/system/stop_logger")
def stop_logger():
    """
    Terminates the background Kite Data Logger process.
    """
    if not is_process_running("run_data_logger.py"):
        return JSONResponse({"status": "error", "message": "Data Logger is already stopped."})
        
    subprocess.run("pkill -f run_data_logger.py", shell=True)
    return JSONResponse({"status": "success", "message": "Kite Data Logger engine stopped."})

@app.post("/api/system/start_engine")
async def start_engine(request: Request):
    """
    Launches the Kite Execution Core strategy engine.
    Supports payload parameter:
    - mode: "dry" (default simulator) or "live" (real capital execution)
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
        
    mode = data.get("mode", "dry").lower()
    
    if is_process_running("kite_execution_core.py"):
        return JSONResponse({"status": "error", "message": "Execution Core is already running."})
        
    venv_py = get_python_executable()
    script_path = os.path.join(config.BACKEND_DIR, "kite_execution_core.py")
    
    cmd = [venv_py, "-u", script_path]
    # Default execution is dry run; only pass 'live' explicitly if selected
    if mode == "live":
        cmd.append("live")
        
    with open(config.ENGINE_LOG, "a") as log_file:
        subprocess.Popen(
            cmd,
            cwd=config.BACKEND_DIR,
            stdout=log_file,
            stderr=log_file
        )
        
    mode_str = "LIVE REAL-MONEY" if mode == "live" else "DRY-RUN SIMULATION"
    return JSONResponse({"status": "success", "message": f"Kite Execution Core started in {mode_str} mode."})

@app.post("/api/system/stop_engine")
def stop_engine():
    """
    Terminates the background strategy execution engine process.
    """
    if not is_process_running("kite_execution_core.py"):
        return JSONResponse({"status": "error", "message": "Kite Execution Core is already stopped."})
        
    subprocess.run("pkill -f kite_execution_core.py", shell=True)
    return JSONResponse({"status": "success", "message": "Kite Execution Core stopped."})

@app.post("/api/system/start_all")
def start_all():
    """
    Convenience method to spin up both components (Logger & Dry-Run Engine).
    """
    logger_started = False
    engine_started = False
    
    venv_py = get_python_executable()
    
    if not is_process_running("run_data_logger.py"):
        script_logger = os.path.join(config.BACKEND_DIR, "run_data_logger.py")
        with open(config.ENGINE_LOG, "a") as log_file:
            subprocess.Popen([venv_py, "-u", script_logger], cwd=config.BACKEND_DIR, stdout=log_file, stderr=log_file)
        logger_started = True
            
    if not is_process_running("kite_execution_core.py"):
        script_engine = os.path.join(config.BACKEND_DIR, "kite_execution_core.py")
        with open(config.ENGINE_LOG, "a") as log_file:
            subprocess.Popen([venv_py, "-u", script_engine], cwd=config.BACKEND_DIR, stdout=log_file, stderr=log_file)
        engine_started = True
        
    return JSONResponse({
        "status": "success", 
        "message": f"Startup executed. Logger started: {logger_started}, Engine started: {engine_started}"
    })

@app.post("/api/system/stop_all")
def stop_all():
    """
    Convenience method to stop all trading engines.
    """
    p1 = subprocess.run("pkill -f run_data_logger.py", shell=True)
    p2 = subprocess.run("pkill -f kite_execution_core.py", shell=True)
    return JSONResponse({
        "status": "success",
        "message": "All background processes terminated successfully."
    })


# -------------------------------------------------------------
# ZERODHA AUTHENTICATION HANDLERS
# -------------------------------------------------------------
@app.get("/api/kite/auth_url")
def get_auth_url():
    """
    Exposes the Zerodha Kite redirect authorization URL.
    """
    needs_login, auth_url = check_kite_auth()
    return JSONResponse({"needs_login": needs_login, "auth_url": auth_url})

@app.get("/kite_auth")
def kite_auth_callback(request_token: str = None):
    """
    Redirect endpoint for Zerodha authentication callback.
    Exchanges request_token for daily access token.
    """
    if not request_token:
        return JSONResponse({"status": "error", "message": "No request token provided"}, status_code=400)
        
    success, message = exchange_kite_token(request_token)
    if success:
        return JSONResponse({"status": "success", "message": message})
    return JSONResponse({"status": "error", "message": message}, status_code=500)


# -------------------------------------------------------------
# WATCHLIST & SCANNER OPERATIONS
# -------------------------------------------------------------
@app.get("/api/watchlist")
def get_watchlist():
    """
    Returns the parsed watchlist.
    """
    return JSONResponse(load_watchlist())

@app.get("/api/search")
def search_tickers(q: str = ""):
    """
    Filters the whitelisted Nifty 50 tickers based on the search query.
    """
    query = q.strip().upper()
    if not query:
        return JSONResponse([])
        
    results = []
    for ticker in config.NIFTY_50_TICKERS:
        if query in ticker:
            results.append({"ticker": ticker, "name": f"{ticker} (NSE Equity)"})
            
    return JSONResponse(results[:10])

@app.post("/api/watchlist/add")
async def add_to_watchlist(request: Request):
    """
    Adds a symbol to the Buy or Sell watchlist columns.
    Ensures a symbol only exists in one column at a time.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol", "").upper()
        direction = data.get("direction", "buy").lower()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not symbol or symbol not in config.NIFTY_50_TICKERS:
        return JSONResponse({"status": "error", "message": "Invalid or non-whitelisted symbol"}, status_code=400)
        
    if direction not in ["buy", "sell"]:
        direction = "buy"
        
    watchlist = load_watchlist()
    
    # Remove from other column if present to prevent duplicates
    other_dir = "sell" if direction == "buy" else "buy"
    if symbol in watchlist.get(other_dir, []):
        watchlist[other_dir].remove(symbol)
        
    if symbol not in watchlist.get(direction, []):
        watchlist[direction].append(symbol)
        
    with open(config.WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=4)
        
    return JSONResponse({"status": "success", "message": f"Added {symbol} to {direction} watchlist."})

@app.post("/api/watchlist/remove")
async def remove_from_watchlist(request: Request):
    """
    Removes a symbol from all watchlist columns.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol", "").upper()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    watchlist = load_watchlist()
    removed = False
    
    for direction in ["buy", "sell"]:
        if symbol in watchlist.get(direction, []):
            watchlist[direction].remove(symbol)
            removed = True
            
    if removed:
        with open(config.WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f, indent=4)
        return JSONResponse({"status": "success", "message": f"Removed {symbol} from watchlist."})
        
    return JSONResponse({"status": "error", "message": f"Symbol {symbol} not found in watchlist."}, status_code=404)

@app.get("/api/watchlist/data")
def get_watchlist_data():
    """
    Returns live prices and pre-calculated technical indicators for watchlisted tickers.
    Reads metrics directly from the shared memory file generated by KiteDataLogger.
    """
    watchlist = load_watchlist()
    buy_symbols = watchlist.get("buy", [])
    sell_symbols = watchlist.get("sell", [])
    all_symbols = list(set(buy_symbols + sell_symbols))
    
    market_snapshot = {}
    if os.path.exists(config.LIVE_MARKET_DATA_FILE):
        try:
            with open(config.LIVE_MARKET_DATA_FILE, "r") as f:
                market_snapshot = json.load(f)
        except Exception:
            pass
            
    results = []
    for symbol in all_symbols:
        direction = "BUY" if symbol in buy_symbols else "SELL"
        symbol_data = market_snapshot.get(symbol, {})
        
        # Merge technical data if available, otherwise return empty placeholders
        ticker_metrics = {
            "symbol": symbol,
            "direction": direction,
            "ltp": symbol_data.get("ltp", None),
            "change": symbol_data.get("change", 0.0),
            "volume": symbol_data.get("volume", 0),
            "adr_percentage": symbol_data.get("adr_percentage", 0.0),
            "adr_absolute": symbol_data.get("adr_absolute", 0.0),
            
            # Timeframe: 5-minute indicators
            "m5_vwap": symbol_data.get("vwap_5m", None),
            "m5_ema20": symbol_data.get("ema20_5m", None),
            "m5_ema50": symbol_data.get("ema50_5m", None),
            "m5_ema200": symbol_data.get("ema200_5m", None),
            "m5_rsi": symbol_data.get("rsi_5m", None),
            
            # Timeframe: 15-minute indicators
            "m15_vwap": symbol_data.get("vwap_15m", None),
            "m15_ema20": symbol_data.get("ema20_15m", None),
            "m15_ema50": symbol_data.get("ema50_15m", None),
            "m15_ema200": symbol_data.get("ema200_15m", None),
            "m15_rsi": symbol_data.get("rsi_15m", None),
            
            "last_update": symbol_data.get("last_update", None)
        }
        results.append(ticker_metrics)
        
    return JSONResponse({"watchlist_data": results})


def load_symbol_to_token():
    """Reads symbol to token mappings from cached file."""
    if os.path.exists(config.INSTRUMENT_MAPPING_FILE):
        try:
            with open(config.INSTRUMENT_MAPPING_FILE, "r") as f:
                mappings = json.load(f)
                return {k: int(v) for k, v in mappings.get("symbol_to_token", {}).items()}
        except Exception:
            pass
    return {}


@app.get("/api/history/{symbol}")
def get_history(symbol: str, interval: str = "5minute", days: int = 5):
    """
    Returns historical candle data from Zerodha for the specified symbol and interval.
    Format is formatted specifically for TradingView Lightweight Charts.
    """
    from datetime import timedelta
    symbol = symbol.upper()
    sym_to_tok = load_symbol_to_token()
    token = sym_to_tok.get(symbol)
    if not token:
        return JSONResponse({"status": "error", "message": f"Symbol {symbol} token mapping not found."}, status_code=400)
        
    try:
        from kite_auth_manager import get_kite_client
        kite = get_kite_client()
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        
        # Verify call parameters against local connect.py reference
        # historical_data(self, instrument_token, from_date, to_date, interval, continuous=False, oi=False)
        data = kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval=interval
        )
        
        formatted_data = []
        for d in data:
            dt = d["date"]
            timestamp = int(dt.timestamp())
            formatted_data.append({
                "time": timestamp,
                "open": d["open"],
                "high": d["high"],
                "low": d["low"],
                "close": d["close"],
                "volume": d["volume"]
            })
            
        return JSONResponse({"status": "success", "data": formatted_data})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# -------------------------------------------------------------
# ZERODHA POSITION & ORDER TELEMETRY
# -------------------------------------------------------------
@app.get("/api/kite/orders")
def api_orders():
    """
    Returns active & historical Zerodha orders.
    """
    return JSONResponse({"orders": get_kite_orders()})

@app.get("/api/kite/positions")
def api_positions():
    """
    Fetches open positions from Zerodha and enriches them with:
    - Stop Loss and Target orders linked to the position
    - Real-time ADR (Average Daily Range) exhaustion metrics
    - Total absolute risk (INR) and risk % matching NJ's ₹2,500 guidelines
    """
    positions = get_kite_positions()
    orders = get_kite_orders()
    
    # Load execution core's target/SL state mappings
    engine_active_trades = {}
    if os.path.exists(config.ACTIVE_TRADES_FILE):
        try:
            with open(config.ACTIVE_TRADES_FILE, "r") as f:
                engine_active_trades = json.load(f)
        except Exception:
            pass
            
    # Load live market data file for ADR calculations
    market_snapshot = {}
    if os.path.exists(config.LIVE_MARKET_DATA_FILE):
        try:
            with open(config.LIVE_MARKET_DATA_FILE, "r") as f:
                market_snapshot = json.load(f)
        except Exception:
            pass

    enriched_positions = []
    
    for pos in positions:
        symbol = pos["symbol"]
        qty = pos["quantity"]
        avg_price = pos["average_price"]
        
        # Calculate live PnL based on latest market price if holding active units
        last_price = pos.get("last_price", 0.0)
        # Verify if we have a fresher price in the live websocket logger
        if symbol in market_snapshot:
            ws_price = market_snapshot[symbol].get("ltp")
            if ws_price:
                last_price = ws_price
                
        pnl = pos.get("pnl", 0.0)
        if qty != 0 and last_price > 0:
            pnl = (pos.get("sell_value", 0.0) - pos.get("buy_value", 0.0)) + (qty * last_price)
            
        pnl_pct = 0.0
        if qty != 0 and avg_price > 0:
            pnl_pct = (pnl / (avg_price * abs(qty))) * 100.0
            
        # 1. Match active orders to link bracket stops (Target Limit and Trigger SL)
        target_price = None
        target_order_id = None
        target_status = None
        
        sl_price = None
        sl_order_id = None
        sl_status = None
        sl_order_type = None
        
        expected_tx = "SELL" if qty > 0 else "BUY"
        open_statuses = ["OPEN", "TRIGGER PENDING"]
        
        for o in orders:
            if o.get("symbol") == symbol and o.get("status") in open_statuses:
                if o.get("transaction_type") == expected_tx:
                    otype = o.get("order_type")
                    if otype == "LIMIT":
                        target_price = o.get("price")
                        target_order_id = o.get("order_id")
                        target_status = o.get("status")
                    elif otype in ["SL", "SL-M"]:
                        sl_price = o.get("trigger_price") or o.get("price")
                        sl_order_id = o.get("order_id")
                        sl_status = o.get("status")
                        sl_order_type = otype
                        
        # 2. Get local engine properties
        trade_details = engine_active_trades.get(symbol, {})
        engine_target = trade_details.get("target")
        engine_sl = trade_details.get("sl")
        strategy = trade_details.get("strategy", "UNTRACKED")
        entry_time = trade_details.get("entry_time", None)

        # 3. ADR Metrics
        adr_val = 0.0
        adr_abs_val = 0.0
        today_open = None
        today_high = None
        today_low = None
        
        symbol_market = market_snapshot.get(symbol, {})
        if symbol_market:
            adr_val = symbol_market.get("adr_percentage", 0.0)
            adr_abs_val = symbol_market.get("adr_absolute", 0.0)
            # Use current LTP to calculate range boundaries
            today_high = last_price
            today_low = last_price
            
        # Calculate dynamic range expansion
        today_range = 0.0
        adr_exhaustion_pct = 0.0
        if adr_abs_val and adr_abs_val > 0 and last_price > 0:
            # Look at daily high/low boundaries if we have them
            if qty > 0: # Long
                # Exhaustion based on progress toward target
                today_range = max(0.0, last_price - avg_price)
            else: # Short
                today_range = max(0.0, avg_price - last_price)
            adr_exhaustion_pct = (today_range / adr_abs_val) * 100.0

        # 4. Risk Assessments (₹2500 max limit)
        allocated_risk = 0.0
        risk_pct = 0.0
        
        effective_sl = sl_price or engine_sl
        if qty != 0:
            if effective_sl:
                allocated_risk = abs(qty * (avg_price - effective_sl))
                risk_pct = min(100.0, (allocated_risk / config.RISK_PER_TRADE) * 100.0)
            elif adr_abs_val:
                # Mock risk if no stop placed
                allocated_risk = abs(qty * adr_abs_val)
                risk_pct = min(100.0, (allocated_risk / config.RISK_PER_TRADE) * 100.0)

        # 5. Risk-Reward Ratio (R:R)
        rr_ratio = 0.0
        effective_target = target_price or engine_target
        if qty != 0 and effective_sl and effective_target:
            reward_dist = abs(effective_target - avg_price)
            risk_dist = abs(avg_price - effective_sl)
            if risk_dist > 0:
                rr_ratio = reward_dist / risk_dist

        # 6. Distance to targets in % and Rs
        dist_to_target_pct = None
        dist_to_sl_pct = None
        target_dist_rs = None
        sl_dist_rs = None
        
        if qty != 0 and last_price > 0:
            if qty > 0: # Long
                if effective_target:
                    target_dist_rs = effective_target - last_price
                    dist_to_target_pct = (target_dist_rs / last_price) * 100.0
                if effective_sl:
                    sl_dist_rs = last_price - effective_sl
                    dist_to_sl_pct = (sl_dist_rs / last_price) * 100.0
            else: # Short
                if effective_target:
                    target_dist_rs = last_price - effective_target
                    dist_to_target_pct = (target_dist_rs / last_price) * 100.0
                if effective_sl:
                    sl_dist_rs = effective_sl - last_price
                    dist_to_sl_pct = (sl_dist_rs / last_price) * 100.0

        enriched_positions.append({
            "symbol": symbol,
            "quantity": qty,
            "average_price": round(avg_price, 2),
            "last_price": round(last_price, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "product": pos.get("product"),
            "strategy": strategy,
            "entry_time": entry_time,
            
            # Stop loss & Limit brackets
            "target_price": target_price,
            "target_order_id": target_order_id,
            "target_status": target_status,
            "sl_price": sl_price,
            "sl_order_id": sl_order_id,
            "sl_status": sl_status,
            "sl_order_type": sl_order_type,
            "engine_target": effective_target,
            "engine_sl": effective_sl,
            
            # Risk & Stats
            "adr": round(adr_val, 2),
            "adr_abs": round(adr_abs_val, 2),
            "adr_exhaustion_pct": round(adr_exhaustion_pct, 2),
            "allocated_risk": round(allocated_risk, 2),
            "risk_pct": round(risk_pct, 1),
            "rr_ratio": round(rr_ratio, 2),
            
            # Distance Metrics
            "dist_to_target_pct": round(dist_to_target_pct, 2) if dist_to_target_pct is not None else None,
            "dist_to_sl_pct": round(dist_to_sl_pct, 2) if dist_to_sl_pct is not None else None,
            "target_dist_rs": round(target_dist_rs, 2) if target_dist_rs is not None else None,
            "sl_dist_rs": round(sl_dist_rs, 2) if sl_dist_rs is not None else None
        })
        
    return JSONResponse({"positions": enriched_positions})


# -------------------------------------------------------------
# TRADING ACTIONS & EXITS
# -------------------------------------------------------------
@app.post("/api/kite/panic")
def execute_panic():
    """
    Emergency panic kill switch. Cancels all pending orders and squares off
    all active net positions immediately using marketable limit orders.
    """
    res = panic_square_off()
    # Force cache refresh in telemetry
    get_kite_positions(force=True)
    if res.get("status") == "error":
        return JSONResponse(res, status_code=500)
    return JSONResponse(res)

@app.post("/api/kite/exit_position")
async def execute_exit_position(request: Request):
    """
    Closes a single active position and cancels its pending stop/target brackets.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not symbol:
        return JSONResponse({"status": "error", "message": "Symbol is required"}, status_code=400)
        
    res = exit_single_position(symbol)
    get_kite_positions(force=True)
    if res.get("status") == "error":
        return JSONResponse(res, status_code=500)
    return JSONResponse(res)

@app.post("/api/kite/scale_out")
async def execute_scale_out(request: Request):
    """
    Reduces the position size by 50% to lock in partial profits.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not symbol:
        return JSONResponse({"status": "error", "message": "Symbol is required"}, status_code=400)
        
    res = book_half_position(symbol)
    get_kite_positions(force=True)
    if res.get("status") == "error":
        return JSONResponse(res, status_code=500)
    return JSONResponse(res)

@app.post("/api/kite/modify_sl")
async def execute_modify_sl(request: Request):
    """
    Modifies an active position's Stop Loss trigger and limit orders.
    """
    try:
        data = await request.json()
        symbol = data.get("symbol")
        new_sl = data.get("new_sl_price")
        sl_order_id = data.get("sl_order_id")
        quantity = data.get("quantity")
        transaction_type = data.get("transaction_type")
        product = data.get("product")
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
        
    if not symbol or new_sl is None:
        return JSONResponse({"status": "error", "message": "symbol and new_sl_price are required"}, status_code=400)
        
    res = modify_or_place_sl(
        symbol=symbol,
        new_trigger_price=float(new_sl),
        sl_order_id=sl_order_id,
        quantity=quantity,
        transaction_type=transaction_type,
        product=product
    )
    if res.get("status") == "error":
        return JSONResponse(res, status_code=500)
    return JSONResponse(res)


@app.on_event("startup")
def startup_event():
    """
    Launches background long-polling listener for interactive Telegram Bot controls.
    """
    try:
        from telegram_bot import start_telegram_polling
        start_telegram_polling()
        print("🤖 [Telegram] Background polling thread launched successfully.")
    except Exception as e:
        print(f"❌ [Telegram] Failed to start background polling thread: {e}")


# -------------------------------------------------------------
# MAIN APP EXECUTION
# -------------------------------------------------------------
if __name__ == "__main__":
    # Host on 0.0.0.0 (Tailscale mesh VPN compatibility)
    # Port 8080 as requested in the system architecture
    uvicorn.run("dashboard_app:app", host="0.0.0.0", port=8080, reload=True)
