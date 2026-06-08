import csv
import json
import os
import uuid
from datetime import datetime, timedelta

import config


JOURNAL_FILE = os.path.join(config.DATA_DIR, "trade_journal_events.jsonl")
BLOCKED_DEDUPE_SECONDS = 60


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_key():
    return datetime.now().strftime("%Y-%m-%d")


def parse_timestamp(value):
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def normalize_symbol(value):
    return str(value or "").replace("NSE:", "").replace("-EQ", "").replace("-BE", "").upper()


def is_recent_duplicate_block(event):
    if event.get("event_type") not in {"SIGNAL_BLOCKED", "ENTRY_REJECTED", "ENTRY_TIMEOUT"}:
        return False
    if not os.path.exists(JOURNAL_FILE):
        return False

    cutoff = datetime.now() - timedelta(seconds=BLOCKED_DEDUPE_SECONDS)
    event_key = (
        event.get("event_type"),
        normalize_symbol(event.get("symbol")),
        event.get("strategy") or "",
        event.get("reason") or "",
    )

    try:
        with open(JOURNAL_FILE, "r") as f:
            lines = f.readlines()[-250:]
    except Exception:
        return False

    for line in reversed(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = parse_timestamp(row.get("timestamp"))
        if ts and ts < cutoff:
            break
        row_key = (
            row.get("event_type"),
            normalize_symbol(row.get("symbol")),
            row.get("strategy") or "",
            row.get("reason") or "",
        )
        if row_key == event_key:
            return True
    return False


def append_event(
    event_type,
    symbol=None,
    strategy=None,
    direction=None,
    state=None,
    qty=None,
    price=None,
    order_id=None,
    pnl=None,
    reason=None,
    source="system",
    extra=None,
):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": now_stamp(),
        "symbol": normalize_symbol(symbol),
        "strategy": strategy or "",
        "direction": direction or "",
        "state": state or "",
        "event_type": event_type,
        "qty": qty,
        "price": round(float(price), 2) if price is not None else None,
        "order_id": order_id,
        "pnl": round(float(pnl), 2) if pnl is not None else None,
        "reason": reason or "",
        "source": source,
    }
    if extra:
        event["extra"] = extra

    if is_recent_duplicate_block(event):
        return event

    with open(JOURNAL_FILE, "a") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")
    return event


def read_events(date=None, strategy=None, symbol=None, event_type=None, limit=500):
    events = []
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if date and not str(event.get("timestamp", "")).startswith(date):
                        continue
                    if strategy and event.get("strategy") != strategy:
                        continue
                    if symbol and normalize_symbol(event.get("symbol")) != normalize_symbol(symbol):
                        continue
                    if event_type and event.get("event_type") != event_type:
                        continue
                    events.append(event)
        except Exception:
            events = []
    events.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return events[: int(limit or 500)]


def read_legacy_csv_closed_trades(date=None):
    rows = []
    if not os.path.exists(config.TRADE_JOURNAL_CSV):
        return rows
    try:
        with open(config.TRADE_JOURNAL_CSV, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get("Timestamp", "")
                if date and not ts.startswith(date):
                    continue
                try:
                    pnl = float(row.get("PnL_INR") or 0.0)
                except (TypeError, ValueError):
                    pnl = 0.0
                rows.append({
                    "timestamp": ts,
                    "symbol": normalize_symbol(row.get("Symbol")),
                    "direction": row.get("Direction", ""),
                    "strategy": row.get("Strategy", ""),
                    "pnl": pnl,
                    "reason": row.get("Reason", ""),
                    "source": "legacy_csv",
                })
    except Exception:
        return []
    return rows


def read_closed_trades(date=None):
    date = date or today_key()
    closed = []
    seen = set()
    events = sorted(
        read_events(date=date, event_type="TRADE_CLOSED", limit=10000),
        key=lambda item: item.get("timestamp", ""),
    )
    for event in events:
        try:
            pnl = float(event.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        extra = event.get("extra") if isinstance(event.get("extra"), dict) else {}
        key = (
            normalize_symbol(event.get("symbol")),
            event.get("direction", ""),
            event.get("strategy", ""),
            int(event.get("qty") or 0),
            round(float(extra.get("entry_price") or 0.0), 2),
            round(float(extra.get("exit_price") or event.get("price") or 0.0), 2),
            round(pnl, 2),
        )
        if key in seen:
            continue
        seen.add(key)
        closed.append({
            "timestamp": event.get("timestamp", ""),
            "symbol": normalize_symbol(event.get("symbol")),
            "direction": event.get("direction", ""),
            "strategy": event.get("strategy", ""),
            "pnl": pnl,
            "reason": event.get("reason", ""),
            "source": "jsonl",
        })
    if closed:
        return closed
    return sorted(read_legacy_csv_closed_trades(date), key=lambda item: item["timestamp"])


def record_trade_close(
    symbol,
    direction,
    entry,
    exit_price,
    qty,
    strategy,
    reason,
    source="execution",
    realized_pnl=None,
    order_id=None,
    pnl_pending=False,
):
    estimated_pnl = (exit_price - entry) * qty if direction == "BUY" else (entry - exit_price) * qty
    pnl = None if pnl_pending else (realized_pnl if realized_pnl is not None else estimated_pnl)
    pnl_pct = ((exit_price - entry) / entry) * 100.0 if direction == "BUY" else ((entry - exit_price) / entry) * 100.0
    extra = {
        "entry_price": round(float(entry), 2),
        "exit_price": round(float(exit_price), 2),
        "pnl_pct": round(float(pnl_pct), 2),
    }
    if pnl_pending:
        extra["pnl_status"] = "PNL_PENDING"
    if realized_pnl is not None:
        extra["broker_pnl"] = round(float(realized_pnl), 2)
    return append_event(
        "TRADE_CLOSED",
        symbol=symbol,
        strategy=strategy,
        direction=direction,
        state="CLOSED",
        qty=qty,
        price=exit_price,
        order_id=order_id,
        pnl=pnl,
        reason=reason,
        source=source,
        extra=extra,
    )


def summarize(date=None):
    date = date or today_key()
    events = read_events(date=date, limit=10000)
    closed = read_closed_trades(date)
    wins = [row for row in closed if row["pnl"] > 0]
    losses = [row for row in closed if row["pnl"] < 0]
    blocked = [event for event in events if event.get("event_type") in {"SIGNAL_BLOCKED", "ENTRY_REJECTED", "ENTRY_TIMEOUT"}]
    total_pnl = sum(row["pnl"] for row in closed)
    avg_win = sum(row["pnl"] for row in wins) / len(wins) if wins else 0.0
    avg_loss = sum(row["pnl"] for row in losses) / len(losses) if losses else 0.0
    return {
        "date": date,
        "realized_pnl": round(total_pnl, 2),
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / len(closed)) * 100.0, 1) if closed else 0.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "blocked_signals": len(blocked),
        "events": len(events),
    }
