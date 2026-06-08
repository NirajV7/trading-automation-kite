import os
from dotenv import load_dotenv

# Define workspace backend paths
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BACKEND_DIR, "data")
LOGS_DIR = os.path.join(BACKEND_DIR, "logs")

# Ensure necessary directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Load environment variables
load_dotenv(dotenv_path=os.path.join(BACKEND_DIR, ".env"))

# File paths
KITE_TOKEN_FILE = os.path.join(DATA_DIR, "kite_token.json")
KITE_INSTRUMENTS_CACHE = os.path.join(DATA_DIR, "kite_instruments.csv")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")
TRADE_JOURNAL_CSV = os.path.join(DATA_DIR, "trade_journal.csv")
ACTIVE_TRADES_FILE = os.path.join(DATA_DIR, "active_trades.json")
INSTRUMENT_MAPPING_FILE = os.path.join(DATA_DIR, "instrument_mappings.json")
LIVE_MARKET_DATA_FILE = os.path.join(DATA_DIR, "live_market_data.json")
RADAR_CANDIDATES_FILE = os.path.join(DATA_DIR, "radar_candidates.json")
EXECUTION_STATUS_FILE = os.path.join(DATA_DIR, "execution_status.json")

# Nifty 50 Volume Spike Radar Strategy Parameters
VOLUME_SPIKE_RATIO = 3.0
PRICE_MOMENTUM_PCT = 0.25
ENABLE_RADAR_LIVE_ENTRIES = os.getenv("ENABLE_RADAR_LIVE_ENTRIES", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


# Log paths
ENGINE_LOG = os.path.join(LOGS_DIR, "engine.log")
TICKER_LOG = os.path.join(LOGS_DIR, "ticker.log")
NIFTY_SPIKES_LOG = os.path.join(LOGS_DIR, "nifty_spikes.log")

# Kite API Configuration
KITE_API_KEY = os.getenv("KITE_API_KEY")
KITE_API_SECRET = os.getenv("KITE_API_SECRET")
KITE_REDIRECT_URL = os.getenv("KITE_REDIRECT_URL", "http://127.0.0.1:8000/kite_auth")



# Risk & Capital Configuration (INR - ₹)
RISK_PER_TRADE = 1000.0  # Max loss per trade: ₹1,000 (cautious testing limit)
CAPITAL_ALLOCATION = 500000.0  # Unified ₹5 Lakh Capital Allocation

# Temporary next-week controls. Disable manually after use.
TEMPORARY_PROFIT_BOOKING_ENABLED = True
TEMPORARY_PROFIT_BOOKING_MIN_PNL = 500.0
TEMPORARY_SL_LOSS_CAP_ENABLED = True
TEMPORARY_SL_LOSS_CAP = 500.0

# Nifty 50 Tickers for Live Volumetric Radar
NIFTY_50_TICKERS = [
    "ABB", "AARTIPHARM", "ADANIENT", "ADANIPORTS", "AEGISLOG", "APOLLOHOSP",
    "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BDL",
    "BEL", "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA", "COALINDIA",
    "DIVISLAB", "DRREDDY", "EICHERMOT", "GRASIM", "HAL", "HCLTECH",
    "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK",
    "INDUSTOWER", "IREDA", "ITC", "INDUSINDBK", "INFY", "JAMNAAUTO",
    "JINDALSAW", "JSWSTEEL", "KOTAKBANK", "LODHA", "LTF", "LTM",
    "LT", "LUMAXTECH", "M&M", "MARUTI", "NATIONALUM", "NTPC",
    "NESTLEIND", "ONGC", "PFC", "PERSISTENT", "POWERGRID", "PREMIERENE",
    "RADICO", "RELIANCE", "SBILIFE", "SBIN", "SIEMENS", "SUNPHARMA",
    "TCS", "TATACONSUM", "TMCV", "TATASTEEL", "TECHM", "TECHNOE",
    "TITAN", "ULTRACEMCO", "UPL", "WIPRO", "REDINGTON", "KPRMILL",
    "IGL", "CHENNPETRO", "JBMA", "ANANTRAJ", "LLOYDSME", "J&KBANK",
    "CHOLAFIN", "PATANJALI", "GLENMARK", "LTTS", "AADHARHFC", "INOXGREEN",
    "DELHIVERY", "CHOLAHLDNG", "LTFOODS"
]
