import json
import os
import time
from datetime import datetime

import config
from trade_journal import append_event, normalize_symbol


ORDER_STATES_FILE = os.path.join(config.DATA_DIR, "trade_states.json")
EXIT_LOCKS_DIR = os.path.join(config.DATA_DIR, "exit_locks")
EXIT_LOCK_TTL_SECONDS = 120
EXIT_IN_PROGRESS_STATES = {"EXIT_REQUESTED"}
EXIT_TERMINAL_STATES = {"EXIT_FILLED", "CLOSED"}
EXIT_ALLOWED_STATES = {"ACTIVE", "SL_FAILED", "EXIT_FAILED", "RECONCILED"}

OPEN_STATES = {
    "SIGNAL_DETECTED",
    "PRECHECK_PASSED",
    "ENTRY_SENT",
    "ENTRY_FILLED",
    "SL_PLACED",
    "ACTIVE",
    "EXIT_REQUESTED",
    "SL_FAILED",
    "EXIT_FAILED",
    "RECONCILED",
}

TERMINAL_STATES = {"CLOSED", "BLOCKED", "ENTRY_REJECTED", "ENTRY_TIMEOUT"}

VALID_TRANSITIONS = {
    None: {"SIGNAL_DETECTED", "RECONCILED"},
    "SIGNAL_DETECTED": {"PRECHECK_PASSED", "BLOCKED"},
    "PRECHECK_PASSED": {"ENTRY_SENT", "BLOCKED"},
    "ENTRY_SENT": {"ENTRY_FILLED", "ENTRY_REJECTED", "ENTRY_TIMEOUT"},
    "ENTRY_FILLED": {"SL_PLACED", "SL_FAILED"},
    "SL_PLACED": {"ACTIVE"},
    "ACTIVE": {"EXIT_REQUESTED", "SL_FAILED", "CLOSED"},
    "SL_FAILED": {"SL_PLACED", "ACTIVE", "EXIT_REQUESTED", "CLOSED"},
    "EXIT_REQUESTED": {"EXIT_FILLED", "EXIT_FAILED"},
    "EXIT_FAILED": {"EXIT_REQUESTED", "CLOSED"},
    "EXIT_FILLED": {"CLOSED"},
    "RECONCILED": {"SL_PLACED", "ACTIVE", "SL_FAILED", "EXIT_REQUESTED", "CLOSED"},
    "BLOCKED": {"SIGNAL_DETECTED"},
    "ENTRY_REJECTED": {"SIGNAL_DETECTED"},
    "ENTRY_TIMEOUT": {"SIGNAL_DETECTED"},
    "CLOSED": {"SIGNAL_DETECTED", "RECONCILED"},
}


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_states():
    if not os.path.exists(ORDER_STATES_FILE):
        return {}
    try:
        with open(ORDER_STATES_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_states(states):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    temp_path = f"{ORDER_STATES_FILE}.tmp"
    with open(temp_path, "w") as f:
        json.dump(states, f, indent=4)
    os.replace(temp_path, ORDER_STATES_FILE)



def exit_lock_path(symbol):
    return os.path.join(EXIT_LOCKS_DIR, f"{normalize_symbol(symbol)}.lock")


def read_exit_lock(symbol):
    path = exit_lock_path(symbol)
    try:
        with open(path, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception:
        return {"symbol": normalize_symbol(symbol), "created_epoch": 0, "corrupt": True}


def release_exit_lock(symbol):
    try:
        os.remove(exit_lock_path(symbol))
        return True
    except FileNotFoundError:
        return False


def is_fresh_exit_lock(symbol, ttl_seconds=EXIT_LOCK_TTL_SECONDS):
    data = read_exit_lock(symbol)
    if not data:
        return False, data
    try:
        age = time.time() - float(data.get("created_epoch", 0))
    except (TypeError, ValueError):
        age = ttl_seconds + 1
    return age <= ttl_seconds, data


def acquire_exit_lock(symbol, reason, source, ttl_seconds=EXIT_LOCK_TTL_SECONDS):
    symbol = normalize_symbol(symbol)
    os.makedirs(EXIT_LOCKS_DIR, exist_ok=True)
    path = exit_lock_path(symbol)
    fresh, existing = is_fresh_exit_lock(symbol, ttl_seconds=ttl_seconds)
    if fresh:
        return {"ok": False, "message": f"{symbol} exit already in progress", "lock": existing}
    if existing:
        release_exit_lock(symbol)

    payload = {
        "symbol": symbol,
        "source": source,
        "reason": reason,
        "created_at": now_stamp(),
        "created_epoch": time.time(),
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        fresh, existing = is_fresh_exit_lock(symbol, ttl_seconds=ttl_seconds)
        if fresh:
            return {"ok": False, "message": f"{symbol} exit already in progress", "lock": existing}
        release_exit_lock(symbol)
        fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=4)
    return {"ok": True, "lock": payload}


def begin_exit(symbol, reason, source, price=None, ttl_seconds=EXIT_LOCK_TTL_SECONDS):
    symbol = normalize_symbol(symbol)
    states = load_states()
    state = states.get(symbol)
    current = state.get("state") if state else None

    if current in EXIT_TERMINAL_STATES:
        return {"ok": False, "message": f"{symbol} already closed ({current})", "state": state}

    if current in EXIT_IN_PROGRESS_STATES:
        fresh, lock = is_fresh_exit_lock(symbol, ttl_seconds=ttl_seconds)
        if fresh:
            return {"ok": False, "message": f"{symbol} exit already requested", "state": state, "lock": lock}
        release_exit_lock(symbol)
        lock_res = acquire_exit_lock(symbol, reason, source, ttl_seconds=ttl_seconds)
        if not lock_res.get("ok"):
            return lock_res
        return {"ok": True, "message": f"{symbol} exit retry acquired", "state": state, "lock": lock_res.get("lock")}

    if current not in EXIT_ALLOWED_STATES:
        return {"ok": False, "message": f"{symbol} state {current} cannot begin exit", "state": state}

    lock_res = acquire_exit_lock(symbol, reason, source, ttl_seconds=ttl_seconds)
    if not lock_res.get("ok"):
        return lock_res

    transition = transition_trade(symbol, "EXIT_REQUESTED", event_type="EXIT_REQUESTED", reason=reason, source=source, price=price)
    if not transition.get("ok"):
        release_exit_lock(symbol)
        return transition
    transition["lock"] = lock_res.get("lock")
    return transition


def finish_exit(symbol, success, reason, source, price=None, order_id=None):
    if success:
        res = transition_trade(symbol, "EXIT_FILLED", event_type="EXIT_FILLED", reason=reason, source=source, price=price, order_id=order_id)
    else:
        res = transition_trade(symbol, "EXIT_FAILED", event_type="EXIT_FAILED", reason=reason, source=source, price=price, order_id=order_id)
    release_exit_lock(symbol)
    return res


def has_open_trade(symbol):
    state = load_states().get(normalize_symbol(symbol), {})
    return state.get("state") in OPEN_STATES


def get_trade_state(symbol):
    return load_states().get(normalize_symbol(symbol))


def start_trade(symbol, strategy, direction, qty=None, price=None, sl=None, target=None, source="strategy"):
    symbol = normalize_symbol(symbol)
    states = load_states()
    existing = states.get(symbol)
    if existing and existing.get("state") in OPEN_STATES:
        return {"ok": False, "message": f"{symbol} already has open state {existing.get('state')}", "state": existing}

    state = {
        "symbol": symbol,
        "strategy": strategy,
        "direction": direction,
        "state": "SIGNAL_DETECTED",
        "qty": qty,
        "entry_price": price,
        "sl": sl,
        "target": target,
        "entry_order_id": None,
        "sl_order_id": None,
        "updated_at": now_stamp(),
        "created_at": now_stamp(),
        "last_reason": "Signal detected",
    }
    states[symbol] = state
    save_states(states)
    append_event("SIGNAL_DETECTED", symbol=symbol, strategy=strategy, direction=direction, state="SIGNAL_DETECTED", qty=qty, price=price, reason="Signal detected", source=source)
    return {"ok": True, "state": state}


def transition_trade(symbol, new_state, event_type=None, reason=None, source="execution", **updates):
    symbol = normalize_symbol(symbol)
    states = load_states()
    state = states.get(symbol)
    current = state.get("state") if state else None
    if new_state not in VALID_TRANSITIONS.get(current, set()):
        return {"ok": False, "message": f"Invalid transition {current} -> {new_state}", "state": state}

    if state is None:
        state = {"symbol": symbol, "created_at": now_stamp()}
    state.update(updates)
    state["state"] = new_state
    state["updated_at"] = now_stamp()
    state["last_reason"] = reason or new_state
    states[symbol] = state
    save_states(states)

    append_event(
        event_type or new_state,
        symbol=symbol,
        strategy=state.get("strategy"),
        direction=state.get("direction"),
        state=new_state,
        qty=state.get("qty"),
        price=updates.get("price") if "price" in updates else state.get("entry_price"),
        order_id=updates.get("order_id") or state.get("entry_order_id") or state.get("sl_order_id"),
        reason=reason or new_state,
        source=source,
    )
    return {"ok": True, "state": state}


def reconcile_trade(symbol, direction, qty, entry_price, sl, target, sl_order_id=None, strategy="RECONCILED"):
    symbol = normalize_symbol(symbol)
    states = load_states()
    state = {
        "symbol": symbol,
        "strategy": strategy,
        "direction": direction,
        "state": "RECONCILED",
        "qty": abs(int(qty)),
        "entry_price": entry_price,
        "sl": sl,
        "target": target,
        "entry_order_id": None,
        "sl_order_id": sl_order_id,
        "updated_at": now_stamp(),
        "created_at": now_stamp(),
        "last_reason": "Broker position imported",
    }
    states[symbol] = state
    save_states(states)
    append_event("RECONCILED", symbol=symbol, strategy=strategy, direction=direction, state="RECONCILED", qty=abs(int(qty)), price=entry_price, order_id=sl_order_id, reason="Broker position imported", source="reconciler")
    return state


def close_trade(symbol, reason="Closed", source="execution"):
    return transition_trade(symbol, "CLOSED", event_type="STATE_CLOSED", reason=reason, source=source)


def get_states():
    return load_states()
