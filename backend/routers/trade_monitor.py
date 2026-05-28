from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from order_state_machine import get_states
from risk_governor import get_status
from symbol_cooldowns import get_active_cooldowns
from trade_journal import read_events, summarize, today_key


router = APIRouter()


def strategy_filter(event, card_key):
    strategy = event.get("strategy")
    direction = event.get("direction")
    if card_key == "ORB":
        return strategy == "ORB"
    if card_key == "NIFTY_RADAR":
        return strategy == "RADAR"
    if card_key == "BUY_WATCHLIST":
        return strategy == "ORB" and direction == "BUY"
    if card_key == "SELL_WATCHLIST":
        return strategy == "ORB" and direction == "SELL"
    return False


def build_strategy_card(card_key, label, events, states, cooldowns, governor):
    relevant = [event for event in events if strategy_filter(event, card_key)]
    closed = [event for event in relevant if event.get("event_type") == "TRADE_CLOSED"]
    blocked = [event for event in relevant if event.get("event_type") in {"SIGNAL_BLOCKED", "ENTRY_REJECTED", "ENTRY_TIMEOUT"}]
    active_states = []
    for state in states.values():
        if card_key == "ORB" and state.get("strategy") == "ORB":
            active_states.append(state)
        elif card_key == "NIFTY_RADAR" and state.get("strategy") == "RADAR":
            active_states.append(state)
        elif card_key == "BUY_WATCHLIST" and state.get("strategy") == "ORB" and state.get("direction") == "BUY":
            active_states.append(state)
        elif card_key == "SELL_WATCHLIST" and state.get("strategy") == "ORB" and state.get("direction") == "SELL":
            active_states.append(state)

    pnl = sum(float(event.get("pnl") or 0.0) for event in closed)
    blockers = []
    if governor.get("status") == "HALTED":
        blockers.extend([reason.get("code") for reason in governor.get("state", {}).get("halt_reasons", [])])
    for item in cooldowns.values():
        if item.get("strategy") in {"", "ORB", "RADAR"}:
            blockers.append(f"COOLDOWN:{item.get('symbol')}")

    status = "HEALTHY"
    if governor.get("status") == "HALTED" or any(state.get("state") in {"SL_FAILED", "EXIT_FAILED"} for state in active_states):
        status = "BLOCKED"
    elif blockers or blocked:
        status = "DEGRADED"

    return {
        "key": card_key,
        "label": label,
        "status": status,
        "last_signal": next((event for event in relevant if event.get("event_type") == "SIGNAL_DETECTED"), None),
        "last_trade": closed[0] if closed else None,
        "trades_today": len(closed),
        "blocked_count": len(blocked),
        "pnl": round(pnl, 2),
        "active_states": active_states,
        "blockers": blockers[:8],
    }


@router.get("/api/trade-journal")
def api_trade_journal(
    date: str = Query(default=None),
    strategy: str = Query(default=None),
    symbol: str = Query(default=None),
    event_type: str = Query(default=None),
    limit: int = Query(default=500),
):
    return JSONResponse({
        "events": read_events(date=date or today_key(), strategy=strategy or None, symbol=symbol or None, event_type=event_type or None, limit=limit)
    })


@router.get("/api/trade-journal/summary")
def api_trade_journal_summary(date: str = Query(default=None)):
    return JSONResponse({"summary": summarize(date or today_key())})


@router.get("/api/order-states")
def api_order_states():
    return JSONResponse({"states": get_states()})


@router.get("/api/symbol-cooldowns")
def api_symbol_cooldowns():
    return JSONResponse({"cooldowns": get_active_cooldowns()})


@router.get("/api/strategy-health")
def api_strategy_health(date: str = Query(default=None)):
    date = date or today_key()
    events = read_events(date=date, limit=10000)
    states = get_states()
    cooldowns = get_active_cooldowns()
    governor = get_status(evaluate=False)
    cards = [
        build_strategy_card("ORB", "ORB Strategy", events, states, cooldowns, governor),
        build_strategy_card("NIFTY_RADAR", "Nifty 50 Radar", events, states, cooldowns, governor),
        build_strategy_card("BUY_WATCHLIST", "Buy Watchlist", events, states, cooldowns, governor),
        build_strategy_card("SELL_WATCHLIST", "Sell Watchlist", events, states, cooldowns, governor),
    ]
    if governor.get("status") == "HALTED":
        overall = "BLOCKED"
    elif any(card["status"] == "BLOCKED" for card in cards):
        overall = "BLOCKED"
    elif any(card["status"] == "DEGRADED" for card in cards):
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"
    return JSONResponse({
        "status": overall,
        "date": date,
        "cards": cards,
        "cooldowns": cooldowns,
        "governor": governor,
        "summary": summarize(date),
    })
