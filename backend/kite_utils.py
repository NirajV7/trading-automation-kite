import os
import urllib.request
from config import KITE_TOKEN_FILE, NIFTY_50_TICKERS

def get_tick_size(price):
    """
    Calculates the dynamic NSE tick size based on the stock's price range.
    
    Tick size rules for NSE Equities:
    - Less than ₹250: 0.01 tick
    - ₹250 to ₹1000: 0.05 tick
    - ₹1000 to ₹5000: 0.10 tick
    - ₹5000 to ₹10000: 0.50 tick
    - ₹10000 to ₹20000: 1.00 tick
    - Greater than ₹20000: 5.00 tick
    """
    if price < 250:
        return 0.01
    elif price <= 1000:
        return 0.05
    elif price <= 5000:
        return 0.10
    elif price <= 10000:
        return 0.50
    elif price <= 20000:
        return 1.00
    else:
        return 5.00

def round_to_tick(price, tick_size=None):
    """
    Rounds a raw float price to the nearest valid NSE tick size increment.
    This prevents Zerodha from rejecting orders due to invalid price steps.
    """
    if tick_size is None:
        tick_size = get_tick_size(price)
    return round(round((price + 1e-9) / tick_size) * tick_size, 2)

def handle_auth_failure(e):
    """
    Checks if a caught exception is a token authentication or permission failure.
    If it is, deletes the cached daily token file so that a fresh authentication
    run is triggered on the next request.
    """
    try:
        import kiteconnect.exceptions as ex
        is_auth_err = False
        if isinstance(e, (ex.TokenException, ex.PermissionException)):
            is_auth_err = True
        else:
            err_msg = str(e).lower()
            if "incorrect" in err_msg or "token" in err_msg or "auth" in err_msg or "api_key" in err_msg:
                is_auth_err = True
                
        if is_auth_err:
            print("⚠️ [Kite Auth] Stale or invalid session token detected. Deleting cached token to trigger re-auth.")
            if os.path.exists(KITE_TOKEN_FILE):
                os.remove(KITE_TOKEN_FILE)
    except Exception as helper_err:
        print(f"⚠️ [Kite Auth] Error in auth failure handler: {helper_err}")

def get_public_ip():
    """
    Fetches the public IPv4 and IPv6 addresses of the host.
    Checks them against the whitelisted IPs specified in the auth mesh configs.
    """
    from kite_auth_manager import KITE_WHITELISTED_IPS
    
    ipv4 = None
    ipv6 = None
    
    # Fetch IPv4 address
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=1.0) as response:
            ipv4 = response.read().decode("utf-8").strip()
    except Exception:
        pass
        
    # Fetch IPv6 address
    try:
        with urllib.request.urlopen("https://api6.ipify.org", timeout=1.0) as response:
            ipv6 = response.read().decode("utf-8").strip()
    except Exception:
        pass

    is_whitelisted = False
    matched_ip = None
    
    if ipv4 and ipv4 in KITE_WHITELISTED_IPS:
        is_whitelisted = True
        matched_ip = ipv4
    elif ipv6 and ipv6 in KITE_WHITELISTED_IPS:
        is_whitelisted = True
        matched_ip = ipv6
        
    return {
        "ipv4": ipv4 or "Offline/Unavailable",
        "ipv6": ipv6 or "Offline/Unavailable",
        "is_whitelisted": is_whitelisted,
        "matched_ip": matched_ip
    }
