import copy
import json
import os
import threading
from datetime import datetime, time as datetime_time

import config
from order_state_machine import get_states
from trade_journal import read_closed_trades
from market_data_guard import newest_live_tick_age_seconds


RISK_GOVERNOR_FILE = os.path.join(config.DATA_DIR, "risk_governor.json")
BROKER_LOCAL_MISMATCH_GRACE_SECONDS = 10

DEFAULT_SETTINGS = {
    "enabled": True,
    "daily_loss_limit": 2000.0,
    "max_consecutive_losses": 2,
    "max_trades_per_day": 5,
    "max_open_positions": 3,
    "stale_market_data_threshold_seconds": 15,
    "halt_on_missing_sl": True,
    "halt_on_broker_local_mismatch": True,
    "halt_on_kite_auth_loss": True,
    "halt_on_stale_market_data": True,
    "one_symbol_loss_lockout": True,
}

DEFAULT_STATE = {
    "halted": False,
    "halt_reasons": [],
    "manual_halt": False,
    "updated_at": None,
}

COUNT_SETTINGS = {
    "max_consecutive_losses",
    "max_trades_per_day",
    "max_open_positions",
    "stale_market_data_threshold_seconds",
}

BOOLEAN_TRUE_VALUES = {"1", "true", "yes", "on"}
BOOLEAN_FALSE_VALUES = {"0", "false", "no", "off"}


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_stamp(value):
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def age_seconds(value):
    dt = parse_stamp(value)
    if not dt:
        return None
    return (datetime.now() - dt).total_seconds()


def today_key():
    return datetime.now().strftime("%Y-%m-%d")


def is_market_window():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return datetime_time(9, 15) <= now.time() <= datetime_time(15, 30)


def coerce_bool(value, default):
    if isinstance(value, bool):
        return value, False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in BOOLEAN_TRUE_VALUES:
            return True, False
        if normalized in BOOLEAN_FALSE_VALUES:
            return False, False
    return default, True


def sanitize_settings(raw_settings):
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    repaired = not isinstance(raw_settings, dict)
    raw_settings = raw_settings if isinstance(raw_settings, dict) else {}

    for key, default in DEFAULT_SETTINGS.items():
        if key not in raw_settings:
            repaired = True
            continue

        value = raw_settings.get(key)
        if isinstance(default, bool):
            settings[key], did_repair = coerce_bool(value, default)
            repaired = repaired or did_repair
            continue

        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
            repaired = True

        if key in COUNT_SETTINGS:
            if number < 1:
                number = default
                repaired = True
            settings[key] = int(number)
        else:
            if number <= 0:
                number = default
                repaired = True
            settings[key] = float(number)

    return settings, repaired


def sanitize_state(raw_state):
    state = copy.deepcopy(DEFAULT_STATE)
    repaired = not isinstance(raw_state, dict)
    raw_state = raw_state if isinstance(raw_state, dict) else {}
    state.update(raw_state)
    if not isinstance(state.get("halt_reasons"), list):
        state["halt_reasons"] = []
        repaired = True
    return state, repaired


_lock = threading.RLock()


def load_governor():
    with _lock:
        if not os.path.exists(RISK_GOVERNOR_FILE):
            data = {"settings": copy.deepcopy(DEFAULT_SETTINGS), "state": copy.deepcopy(DEFAULT_STATE)}
            save_governor(data)
            return data
        try:
            with open(RISK_GOVERNOR_FILE, "r") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    
        settings, settings_repaired = sanitize_settings(raw.get("settings", {}))
        state, state_repaired = sanitize_state(raw.get("state", {}))
        data = {"settings": settings, "state": state}
        if settings_repaired or state_repaired:
            save_governor(data)
        return data


def save_governor(data):
    with _lock:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        temp_path = f"{RISK_GOVERNOR_FILE}.tmp"
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(temp_path, RISK_GOVERNOR_FILE)


def normalize_symbol(value):
    return str(value or "").replace("NSE:", "").replace("-EQ", "").replace("-BE", "").upper()


def parse_trade_journal():
    try:
        return read_closed_trades(today_key())
    except Exception:
        return []


def count_active_entries_today(active_trades):
    count = 0
    for trade in (active_trades or {}).values():
        if str(trade.get("entry_time", "")).startswith(today_key()):
            count += 1
    return count


def get_consecutive_losses(journal_rows):
    losses = 0
    for row in reversed(journal_rows):
        if row["pnl"] < 0:
            losses += 1
        else:
            break
    return losses


def get_symbol_losses_today(journal_rows):
    symbols = set()
    for row in journal_rows:
        if row["pnl"] < 0 and row["symbol"]:
            symbols.add(row["symbol"])
    return symbols


def get_unrealized_pnl(positions):
    total = 0.0
    for pos in positions or []:
        try:
            if int(pos.get("quantity", 0)) != 0:
                total += float(pos.get("pnl") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def build_metrics(positions=None, active_trades=None):
    rows = parse_trade_journal()
    realized = sum(row["pnl"] for row in rows)
    unrealized = get_unrealized_pnl(positions)
    return {
        "date": today_key(),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "net_pnl": round(realized + unrealized, 2),
        "trades_today": len(rows) + count_active_entries_today(active_trades),
        "closed_trades_today": len(rows),
        "active_trades_today": count_active_entries_today(active_trades),
        "consecutive_losses": get_consecutive_losses(rows),
        "symbol_losses_today": sorted(get_symbol_losses_today(rows)),
    }


def add_halt_reason(code, message, source="risk_governor"):
    data = load_governor()
    state = data["state"]
    existing_codes = {reason.get("code") for reason in state.get("halt_reasons", [])}
    if code not in existing_codes:
        state.setdefault("halt_reasons", []).append({
            "code": code,
            "message": message,
            "source": source,
            "created_at": now_stamp(),
        })
    state["halted"] = True
    state["updated_at"] = now_stamp()
    data["state"] = state
    save_governor(data)
    return data


def manual_halt(message="Manual halt from Kill Switch UI"):
    data = add_halt_reason("MANUAL_HALT", message, source="ui")
    data["state"]["manual_halt"] = True
    save_governor(data)
    return get_status()


def reset_halt():
    data = load_governor()
    data["state"].update({
        "halted": False,
        "halt_reasons": [],
        "manual_halt": False,
        "updated_at": now_stamp(),
    })
    save_governor(data)
    return get_status(evaluate=False)


def update_settings(partial):
    data = load_governor()
    settings = data["settings"]
    for key, value in (partial or {}).items():
        if key not in DEFAULT_SETTINGS:
            continue
        default = DEFAULT_SETTINGS[key]
        if isinstance(default, bool):
            settings[key], _ = coerce_bool(value, default)
        elif isinstance(default, int) and not isinstance(default, bool):
            try:
                number = int(value)
            except (TypeError, ValueError):
                number = default
            settings[key] = max(1, number) if key in COUNT_SETTINGS else max(0, number)
        else:
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = default
            settings[key] = number if number > 0 else float(default)
    data["settings"], _ = sanitize_settings(settings)
    data["state"]["updated_at"] = now_stamp()
    save_governor(data)
    return get_status(evaluate=False)


def reset_settings_to_defaults():
    data = load_governor()
    data["settings"] = copy.deepcopy(DEFAULT_SETTINGS)
    data["state"]["updated_at"] = now_stamp()
    save_governor(data)
    return get_status(evaluate=False)


def is_recent_local_entry(trade):
    age = age_seconds((trade or {}).get("entry_time"))
    return age is not None and age <= BROKER_LOCAL_MISMATCH_GRACE_SECONDS


def is_recent_exit_state(state):
    if (state or {}).get("state") not in {"EXIT_REQUESTED", "EXIT_FILLED", "CLOSED"}:
        return False
    age = age_seconds((state or {}).get("updated_at"))
    return age is not None and age <= BROKER_LOCAL_MISMATCH_GRACE_SECONDS


def check_mismatch(positions, active_trades, states=None):
    broker_symbols = {
        normalize_symbol(pos.get("symbol") or pos.get("tradingsymbol"))
        for pos in positions or []
        if int(pos.get("quantity", 0) or 0) != 0
    }
    local_symbols = {normalize_symbol(sym) for sym in (active_trades or {}).keys()}
    states = states if isinstance(states, dict) else get_states()
    broker_only = sorted(
        sym for sym in broker_symbols - local_symbols
        if sym and not is_recent_exit_state(states.get(sym))
    )
    local_only = sorted(
        sym for sym in local_symbols - broker_symbols
        if sym and not is_recent_local_entry((active_trades or {}).get(sym))
    )
    return broker_only, local_only


def evaluate_rules(positions=None, active_trades=None, auth_needs_login=None):
    data = load_governor()
    settings = data["settings"]
    if not settings.get("enabled", True):
        return data

    metrics = build_metrics(positions, active_trades)
    if metrics["net_pnl"] <= -float(settings["daily_loss_limit"]):
        add_halt_reason(
            "DAILY_LOSS_LIMIT",
            f"Daily net PnL ₹{metrics['net_pnl']:.2f} breached loss limit ₹{float(settings['daily_loss_limit']):.2f}.",
        )

    if metrics["consecutive_losses"] >= int(settings["max_consecutive_losses"]):
        add_halt_reason(
            "CONSECUTIVE_LOSSES",
            f"{metrics['consecutive_losses']} consecutive losses reached.",
        )

    if metrics["trades_today"] >= int(settings["max_trades_per_day"]):
        add_halt_reason(
            "MAX_TRADES_PER_DAY",
            f"{metrics['trades_today']} trades today reached daily cap.",
        )

    if settings.get("halt_on_kite_auth_loss") and auth_needs_login is True:
        add_halt_reason("KITE_AUTH_LOSS", "Kite authentication expired or unavailable.")

    if settings.get("halt_on_stale_market_data") and is_market_window():
        age = newest_live_tick_age_seconds()
        if age is None:
            add_halt_reason("STALE_MARKET_DATA", "Live market data has no fresh symbol ticks during market window.")
        elif age > float(settings["stale_market_data_threshold_seconds"]):
            add_halt_reason("STALE_MARKET_DATA", f"Live market data real ticks stale for {age:.0f}s.")

    if settings.get("halt_on_missing_sl"):
        for symbol, trade in (active_trades or {}).items():
            if trade.get("sl_unprotected") or not trade.get("sl_id"):
                add_halt_reason("MISSING_SL", f"{normalize_symbol(symbol)} has no confirmed protective SL.")
                break

    if settings.get("halt_on_broker_local_mismatch") and positions is not None and active_trades is not None:
        broker_only, local_only = check_mismatch(positions, active_trades)
        if broker_only:
            add_halt_reason("BROKER_LOCAL_MISMATCH", f"Broker position not tracked locally: {', '.join(broker_only)}.")
        elif local_only:
            add_halt_reason("BROKER_LOCAL_MISMATCH", f"Local trade missing broker position: {', '.join(local_only)}.")

    return load_governor()


def can_open_trade(symbol, strategy, active_trades=None, positions=None, auth_needs_login=None):
    data = evaluate_rules(positions=positions, active_trades=active_trades, auth_needs_login=auth_needs_login)
    settings = data["settings"]
    state = data["state"]
    if not settings.get("enabled", True):
        return {"allowed": True, "message": "Risk Governor disabled."}

    if state.get("halted"):
        reasons = state.get("halt_reasons", [])
        reason_text = reasons[0]["message"] if reasons else "Trading halted."
        return {"allowed": False, "message": reason_text, "code": reasons[0].get("code") if reasons else "HALTED"}

    active_count = len(active_trades or {})
    if active_count >= int(settings["max_open_positions"]):
        return {
            "allowed": False,
            "message": f"Max open positions reached: {active_count}/{settings['max_open_positions']}.",
            "code": "MAX_OPEN_POSITIONS",
        }

    metrics = build_metrics(positions, active_trades)
    norm_symbol = normalize_symbol(symbol)
    if settings.get("one_symbol_loss_lockout") and norm_symbol in set(metrics["symbol_losses_today"]):
        return {
            "allowed": False,
            "message": f"{norm_symbol} locked out after loss today.",
            "code": "SYMBOL_LOSS_LOCKOUT",
        }

    return {"allowed": True, "message": f"Risk Governor allowed {strategy} entry for {norm_symbol}."}


def get_status(positions=None, active_trades=None, auth_needs_login=None, evaluate=True):
    if evaluate:
        evaluate_rules(positions=positions, active_trades=active_trades, auth_needs_login=auth_needs_login)
    data = load_governor()
    metrics = build_metrics(positions, active_trades)
    loss_limit = float(data["settings"]["daily_loss_limit"])
    remaining = loss_limit + metrics["net_pnl"]
    if not data["settings"].get("enabled", True):
        status = "DISABLED"
    elif data["state"].get("halted"):
        status = "HALTED"
    else:
        status = "ARMED"
    return {
        "status": status,
        "settings": data["settings"],
        "state": data["state"],
        "metrics": {
            **metrics,
            "daily_loss_limit": loss_limit,
            "remaining_loss_room": round(max(0.0, remaining), 2),
        },
    }
