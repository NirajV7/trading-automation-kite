import math

import config
from kite_utils import get_tick_size
from market_data_guard import get_kite_ltp, is_symbol_live_data_stale


TEMPORARY_PROFIT_REASON = "Temporary Profit Booking ₹500"


def _positive_float(value, default=0.0):
    try:
        value = float(value)
        return value if value > 0 else float(default)
    except (TypeError, ValueError):
        return float(default)


def temporary_profit_threshold():
    return _positive_float(getattr(config, "TEMPORARY_PROFIT_BOOKING_MIN_PNL", 0.0), 0.0)


def temporary_profit_booking_enabled():
    return bool(getattr(config, "TEMPORARY_PROFIT_BOOKING_ENABLED", False)) and temporary_profit_threshold() > 0


def temporary_sl_loss_cap():
    return _positive_float(getattr(config, "TEMPORARY_SL_LOSS_CAP", 0.0), 0.0)


def temporary_sl_cap_enabled():
    return bool(getattr(config, "TEMPORARY_SL_LOSS_CAP_ENABLED", False)) and temporary_sl_loss_cap() > 0


def calculate_trade_pnl(entry, ltp, qty, direction):
    try:
        entry = float(entry)
        ltp = float(ltp)
        qty = abs(int(qty))
        direction = str(direction or "").upper()
    except (TypeError, ValueError):
        return 0.0

    if entry <= 0 or ltp <= 0 or qty <= 0:
        return 0.0
    if direction == "BUY":
        return (ltp - entry) * qty
    if direction == "SELL":
        return (entry - ltp) * qty
    return 0.0


def _round_loss_cap_sl(raw_sl, direction):
    tick_size = get_tick_size(raw_sl)
    direction = str(direction or "").upper()
    if direction == "BUY":
        # Round toward entry so tick rounding does not increase planned loss.
        return round(math.ceil((raw_sl - 1e-9) / tick_size) * tick_size, 2)
    if direction == "SELL":
        return round(math.floor((raw_sl + 1e-9) / tick_size) * tick_size, 2)
    return round(raw_sl, 2)


def calculate_temporary_sl_price(entry_price, qty, direction, fallback_sl=None):
    if not temporary_sl_cap_enabled():
        return fallback_sl

    try:
        entry_price = float(entry_price)
        qty = abs(int(qty))
        direction = str(direction or "").upper()
    except (TypeError, ValueError):
        return fallback_sl

    if entry_price <= 0 or qty <= 0:
        return fallback_sl

    distance = temporary_sl_loss_cap() / qty
    if direction == "BUY":
        raw_sl = entry_price - distance
        if raw_sl <= 0:
            return fallback_sl
    elif direction == "SELL":
        raw_sl = entry_price + distance
    else:
        return fallback_sl

    rounded_sl = _round_loss_cap_sl(raw_sl, direction)
    return rounded_sl if rounded_sl > 0 else fallback_sl


def confirm_temporary_profit_exit(symbol, trade, cached_ltp, threshold_seconds=None):
    threshold = temporary_profit_threshold()
    entry = trade.get("entry")
    qty = trade.get("qty")
    direction = trade.get("direction")

    if not temporary_profit_booking_enabled():
        return {
            "confirmed": False,
            "ltp": cached_ltp,
            "pnl": calculate_trade_pnl(entry, cached_ltp, qty, direction),
            "source": "disabled",
            "stale": False,
            "threshold_pnl": threshold,
            "reason": "Temporary profit booking disabled",
        }

    stale, age, stale_threshold = is_symbol_live_data_stale(symbol, threshold_seconds=threshold_seconds)
    if not stale:
        pnl = calculate_trade_pnl(entry, cached_ltp, qty, direction)
        return {
            "confirmed": pnl >= threshold,
            "ltp": float(cached_ltp),
            "pnl": pnl,
            "source": "cache",
            "stale": False,
            "age_seconds": age,
            "threshold_seconds": stale_threshold,
            "threshold_pnl": threshold,
            "reason": "Cached LTP confirmed temporary profit" if pnl >= threshold else "Cached PnL below temporary profit threshold",
        }

    try:
        fresh_ltp = get_kite_ltp(symbol)
    except Exception as exc:
        return {
            "confirmed": False,
            "ltp": None,
            "pnl": None,
            "source": "kite",
            "stale": True,
            "age_seconds": age,
            "threshold_seconds": stale_threshold,
            "threshold_pnl": threshold,
            "reason": f"Fresh Kite LTP fetch failed: {exc}",
        }

    pnl = calculate_trade_pnl(entry, fresh_ltp, qty, direction)
    confirmed = pnl >= threshold
    return {
        "confirmed": confirmed,
        "ltp": fresh_ltp,
        "pnl": pnl,
        "source": "kite",
        "stale": True,
        "age_seconds": age,
        "threshold_seconds": stale_threshold,
        "threshold_pnl": threshold,
        "reason": "Fresh Kite LTP confirmed temporary profit" if confirmed else "Stale cache profit not confirmed by fresh Kite LTP",
    }
