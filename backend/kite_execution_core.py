import os
import json
import time
from datetime import datetime

from config import (
    NIFTY_50_TICKERS,
    RISK_PER_TRADE,
    CAPITAL_ALLOCATION,
    ACTIVE_TRADES_FILE,
    ENGINE_LOG,
    INSTRUMENT_MAPPING_FILE,
    LIVE_MARKET_DATA_FILE
)
from kite_auth_manager import get_kite_client
from kite_utils import handle_auth_failure

# Import Mixins
from orb_manager import ORBManagerMixin
from order_executor import OrderExecutorMixin
from strategy_evaluator import StrategyEvaluatorMixin
from position_monitor import PositionMonitorMixin
from reconciler import ReconcilerMixin
from radar_strategy import RadarStrategyMixin
from symbol_cooldowns import get_active_cooldowns

# -------------------------------------------------------------
# STUB: Notifications (Telegram removed — log only)
# -------------------------------------------------------------
def send_telegram_alert(message):
    """Stub: logs the alert message. Telegram integration removed."""
    print(f"📢 [ALERT] {message}")


# -------------------------------------------------------------
# CORE EXECUTION SYSTEM CLASS
# -------------------------------------------------------------
class KiteExecutionCore(
    ORBManagerMixin,
    OrderExecutorMixin,
    StrategyEvaluatorMixin,
    PositionMonitorMixin,
    ReconcilerMixin,
    RadarStrategyMixin
):
    """
    Manages strategy evaluations (ORB & Volumetric Spikes), handles risk 
    allocation math, tracks active positions, executes orders (Dry Run or Live),
    and synchronizes execution state with Zerodha.
    """

    def __init__(self, dry_run=True):
        import threading
        self.lock = threading.Lock()
        self.dry_run = dry_run
        self.kite = None
        
        # Load mappings to resolve symbol tokens during setup
        self.symbol_to_token = {}
        self.load_symbol_mappings()
        
        # Local state storage
        self.active_trades = {}  # {SYMBOL: {entry_price, qty, direction, sl, target, sl_id, target_id, strategy}}
        self.cooldowns = {}       # {SYMBOL: cooldown metadata loaded from symbol_cooldowns.json}
        self.orb_ranges = {}      # {SYMBOL: {"high": value, "low": value}}
        self.radar_candidates = {} # {SYMBOL: candidate_details}
        
        # Load existing active trades and radar candidates from disk
        self.load_active_trades()
        self.refresh_cooldowns()
        self.load_radar_candidates()
        self.log_message(f"Execution Core initialized. Mode: {'DRY RUN' if dry_run else 'LIVE'}")

    def refresh_cooldowns(self):
        self.cooldowns = get_active_cooldowns()
        return self.cooldowns

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

    def load_active_trades(self, silent=False):
        """Reads persisted active trades from active_trades.json."""
        if os.path.exists(ACTIVE_TRADES_FILE):
            try:
                with open(ACTIVE_TRADES_FILE, "r") as f:
                    self.active_trades = json.load(f)
                if not silent:
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
                    
                # 2. Reload active trades from disk to synchronize with remote entries (Dashboard)
                self.load_active_trades(silent=True)
                
                # 3. Read live data cache from logger updates
                if os.path.exists(LIVE_MARKET_DATA_FILE):
                    with open(LIVE_MARKET_DATA_FILE, "r") as f:
                        market_snapshot = json.load(f)
                        
                    # Load current watchlist symbols dynamically
                    from config import WATCHLIST_FILE
                    wl_symbols = []
                    if os.path.exists(WATCHLIST_FILE):
                        try:
                            with open(WATCHLIST_FILE, "r") as f:
                                wl = json.load(f)
                            def clean_sym(s):
                                return s.replace("NSE:", "").replace("-EQ", "").replace("-BE", "").upper()
                            wl_symbols = [clean_sym(s) for s in wl.get("buy", []) + wl.get("sell", [])]
                        except Exception:
                            pass
                    
                    active_symbols = list(set(NIFTY_50_TICKERS + wl_symbols))
                    for sym in active_symbols:
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
                            
                            # Evaluate volume spike radar on all active tickers (Nifty 50 + watchlist)
                            self.evaluate_radar_signals(sym, ltp, ticker_data)
                            
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
