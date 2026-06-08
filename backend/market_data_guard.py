import json
import os
import time

import config
from trade_journal import normalize_symbol

DEFAULT_STALE_THRESHOLD_SECONDS = 15
RISK_GOVERNOR_FILE = os.path.join(config.DATA_DIR, "risk_governor.json")


def get_stale_threshold_seconds(default=DEFAULT_STALE_THRESHOLD_SECONDS):
    try:
        with open(RISK_GOVERNOR_FILE, "r") as f:
            data = json.load(f)
        value = data.get("settings", {}).get("stale_market_data_threshold_seconds", default)
        value = float(value)
        return value if value > 0 else float(default)
    except Exception:
        return float(default)


def read_live_market_snapshot():
    try:
        with open(config.LIVE_MARKET_DATA_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def live_data_age_seconds():
    # Kept for compatibility; returns JSON file age, not trusted tick freshness.
    try:
        return time.time() - os.path.getmtime(config.LIVE_MARKET_DATA_FILE)
    except Exception:
        return None


def _tick_epoch_for_symbol(symbol, snapshot=None):
    snapshot = snapshot if isinstance(snapshot, dict) else read_live_market_snapshot()
    item = snapshot.get(normalize_symbol(symbol), {})
    try:
        tick_epoch = float(item.get("tick_epoch"))
    except (TypeError, ValueError):
        return None
    return tick_epoch if tick_epoch > 0 else None


def symbol_tick_age_seconds(symbol, snapshot=None):
    tick_epoch = _tick_epoch_for_symbol(symbol, snapshot=snapshot)
    if tick_epoch is None:
        return None
    return max(0.0, time.time() - tick_epoch)


def newest_live_tick_age_seconds(snapshot=None):
    snapshot = snapshot if isinstance(snapshot, dict) else read_live_market_snapshot()
    newest = None
    for item in snapshot.values():
        if not isinstance(item, dict):
            continue
        try:
            tick_epoch = float(item.get("tick_epoch"))
        except (TypeError, ValueError):
            continue
        if tick_epoch <= 0:
            continue
        newest = tick_epoch if newest is None else max(newest, tick_epoch)
    if newest is None:
        return None
    return max(0.0, time.time() - newest)


def is_symbol_live_data_stale(symbol, threshold_seconds=None, snapshot=None):
    threshold = float(threshold_seconds or get_stale_threshold_seconds())
    age = symbol_tick_age_seconds(symbol, snapshot=snapshot)
    return age is None or age > threshold, age, threshold


def is_live_data_stale(threshold_seconds=None):
    threshold = float(threshold_seconds or get_stale_threshold_seconds())
    age = newest_live_tick_age_seconds()
    return age is None or age > threshold, age, threshold


def get_kite_ltp(symbol, exchange="NSE"):
    from kite_auth_manager import get_kite_client
    kite = get_kite_client()
    symbol = normalize_symbol(symbol)
    key = f"{exchange}:{symbol}"
    data = kite.ltp(key)
    ltp = data.get(key, {}).get("last_price")
    if ltp is None or float(ltp) <= 0:
        raise ValueError(f"Could not fetch fresh LTP for {key}")
    return float(ltp)


def trigger_hit(direction, trigger_price, trigger_type, ltp):
    direction = str(direction or "").upper()
    trigger_type = str(trigger_type or "").lower()
    trigger_price = float(trigger_price)
    ltp = float(ltp)

    if trigger_type == "target":
        return (direction == "BUY" and ltp >= trigger_price) or (direction == "SELL" and ltp <= trigger_price)
    if trigger_type == "sl":
        return (direction == "BUY" and ltp <= trigger_price) or (direction == "SELL" and ltp >= trigger_price)
    raise ValueError(f"Unknown trigger_type: {trigger_type}")


def confirm_exit_trigger(symbol, direction, trigger_price, trigger_type, cached_ltp, threshold_seconds=None):
    stale, age, threshold = is_symbol_live_data_stale(symbol, threshold_seconds=threshold_seconds)
    if not stale:
        return {
            "confirmed": True,
            "ltp": float(cached_ltp),
            "source": "cache",
            "stale": False,
            "age_seconds": age,
            "threshold_seconds": threshold,
        }

    try:
        fresh_ltp = get_kite_ltp(symbol)
    except Exception as exc:
        return {
            "confirmed": False,
            "ltp": None,
            "source": "kite",
            "stale": True,
            "age_seconds": age,
            "threshold_seconds": threshold,
            "reason": f"Fresh Kite LTP fetch failed: {exc}",
        }

    confirmed = trigger_hit(direction, trigger_price, trigger_type, fresh_ltp)
    return {
        "confirmed": confirmed,
        "ltp": fresh_ltp,
        "source": "kite",
        "stale": True,
        "age_seconds": age,
        "threshold_seconds": threshold,
        "reason": "Fresh Kite LTP confirmed trigger" if confirmed else "Stale cache not confirmed by fresh Kite LTP",
    }
