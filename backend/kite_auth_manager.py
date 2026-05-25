import os
import json
from datetime import datetime
# pyrefly: ignore [missing-import]
from kiteconnect import KiteConnect

# Import configuration settings
from config import (
    KITE_TOKEN_FILE,
    KITE_API_KEY,
    KITE_API_SECRET,
    KITE_REDIRECT_URL,
)

# Whitelisted IPs for Zerodha connection audits
KITE_WHITELISTED_IPS = [
    "2401:4900:883a:fb23:799d:9a4b:4b9d:11ba",
    "2409:40f2:3a:8df0:c4a2:bd76:cea3:b353",
    "2409:40f2:103e:8cd7:dea:6b37:43cb:3c4a"
]

def check_kite_auth():
    """
    Validates if the cached session token in `kite_token.json` is still valid for today.
    Force daily refresh only if we crossed into a new day AND it is past 6:00 AM IST (Zerodha session reset).
    
    Returns:
        tuple: (needs_login: bool, auth_url: str)
    """
    def get_new_url():
        return f"https://kite.zerodha.com/connect/login?api_key={KITE_API_KEY}&v=3"

    if not KITE_API_KEY or not KITE_API_SECRET:
        print("⚠️ Missing KITE_API_KEY or KITE_API_SECRET in config/environment.")
        return True, "#"

    if os.path.exists(KITE_TOKEN_FILE):
        with open(KITE_TOKEN_FILE, "r") as f:
            try:
                token_data = json.load(f)
                token_date_str = token_data.get("date")
                if token_date_str:
                    try:
                        token_date = datetime.strptime(token_date_str, "%Y-%m-%d").date()
                        today = datetime.now().date()
                        # Zerodha access tokens expire daily. A new session is needed if a new day has started
                        # and it's past 6:00 AM IST when the backend session reset occurs.
                        if token_date != today and datetime.now().hour >= 6:
                            return True, get_new_url()
                    except Exception as e:
                        print(f"Kite date check fallback error: {e}")
                        return True, get_new_url()
                else:
                    return True, get_new_url()
                
                access_token = token_data.get("access_token")
                if not access_token:
                    return True, get_new_url()
                
                return False, None
            except Exception as e:
                print(f"Kite Auth Check Error: {e}")
                return True, get_new_url()
                
    return True, get_new_url()

def exchange_kite_token(request_token):
    """
    Exchanges the temporary `request_token` from Zerodha login redirect redirect
    for a persistent daily `access_token` and caches it locally.
    """
    if not request_token:
        return False, "Request token cannot be empty"
        
    try:
        kite = KiteConnect(api_key=KITE_API_KEY)
        data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        access_token = data.get("access_token")
        
        if access_token:
            with open(KITE_TOKEN_FILE, "w") as f:
                json.dump({
                    "access_token": access_token,
                    "date": datetime.now().strftime("%Y-%m-%d")
                }, f)
            return True, "Authorized Kite Connect successfully!"
        return False, "Failed to retrieve access token from session data."
    except Exception as e:
        return False, f"Exception during Kite token exchange: {str(e)}"

def get_kite_client():
    """
    Returns an authenticated instance of KiteConnect client using the cached session.
    Raises Exception if session token is invalid or missing (requiring login redirect).
    """
    if not KITE_API_KEY:
        raise ValueError("Kite API Key is not configured in config/environment.")
        
    if not os.path.exists(KITE_TOKEN_FILE):
        raise FileNotFoundError("No active session cached. Perform authentication first.")
        
    with open(KITE_TOKEN_FILE, "r") as f:
        token_data = json.load(f)
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("Cached session contains empty access_token.")
            
        kite = KiteConnect(api_key=KITE_API_KEY)
        kite.set_access_token(access_token)
        return kite
