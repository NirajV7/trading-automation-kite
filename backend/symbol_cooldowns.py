import json
import os
import time
from datetime import datetime

import config
from trade_journal import append_event, normalize_symbol


COOLDOWNS_FILE = os.path.join(config.DATA_DIR, "symbol_cooldowns.json")

LOSS_EXIT_MINUTES = 30
ENTRY_ERROR_MINUTES = 15
MANUAL_RISK_MINUTES = 30


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_cooldowns():
    if not os.path.exists(COOLDOWNS_FILE):
        return {}
    try:
        with open(COOLDOWNS_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cooldowns(data):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    temp_path = f"{COOLDOWNS_FILE}.tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(temp_path, COOLDOWNS_FILE)


def get_active_cooldowns():
    data = load_cooldowns()
    now = time.time()
    active = {}
    changed = False
    for symbol, item in list(data.items()):
        if float(item.get("expires_at_epoch", 0)) > now:
            active[symbol] = item
        else:
            del data[symbol]
            changed = True
    if changed:
        save_cooldowns(data)
    return active


def get_active_cooldown(symbol):
    return get_active_cooldowns().get(normalize_symbol(symbol))


def is_symbol_on_cooldown(symbol):
    return get_active_cooldown(symbol) is not None


def set_cooldown(symbol, minutes, reason, strategy="", source="execution"):
    symbol = normalize_symbol(symbol)
    if minutes <= 0:
        clear_cooldown(symbol)
        return None
    data = load_cooldowns()
    now = time.time()
    item = {
        "symbol": symbol,
        "strategy": strategy,
        "reason": reason,
        "minutes": minutes,
        "created_at": now_stamp(),
        "expires_at_epoch": now + (minutes * 60),
    }
    data[symbol] = item
    save_cooldowns(data)
    append_event("COOLDOWN_SET", symbol=symbol, strategy=strategy, reason=reason, source=source, extra={"minutes": minutes})
    return item


def clear_cooldown(symbol):
    symbol = normalize_symbol(symbol)
    data = load_cooldowns()
    if symbol in data:
        del data[symbol]
        save_cooldowns(data)


def exit_cooldown_minutes(reason, pnl):
    reason_text = str(reason or "").lower()
    pnl = float(pnl or 0.0)
    if "target" in reason_text and pnl > 0:
        return 0
    if pnl < 0 or "stop loss" in reason_text or "sl" in reason_text:
        return LOSS_EXIT_MINUTES
    if "manual" in reason_text or "panic" in reason_text or "unknown" in reason_text or "failed" in reason_text:
        return MANUAL_RISK_MINUTES
    return 0


def entry_error_cooldown(symbol, strategy, reason, source="execution"):
    return set_cooldown(symbol, ENTRY_ERROR_MINUTES, reason, strategy=strategy, source=source)


def apply_exit_cooldown(symbol, strategy, reason, pnl, source="execution"):
    minutes = exit_cooldown_minutes(reason, pnl)
    if minutes <= 0:
        clear_cooldown(symbol)
        return None
    return set_cooldown(symbol, minutes, reason, strategy=strategy, source=source)
