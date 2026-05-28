import json
import os
from datetime import datetime

import config
from trade_journal import append_event, normalize_symbol


ORDER_STATES_FILE = os.path.join(config.DATA_DIR, "trade_states.json")

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
