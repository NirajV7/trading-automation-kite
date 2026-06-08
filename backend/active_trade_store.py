import json
import os
import time
import uuid
from contextlib import contextmanager

import config
from trade_journal import normalize_symbol


LOCK_WAIT_SECONDS = 3.0
LOCK_POLL_SECONDS = 0.05
LOCK_STALE_SECONDS = 10.0


class ActiveTradeStoreError(Exception):
    pass


class ActiveTradeLockTimeout(ActiveTradeStoreError):
    pass


class ActiveTradeFileCorrupt(ActiveTradeStoreError):
    pass


def active_trades_lock_file():
    return f"{config.ACTIVE_TRADES_FILE}.lock"


def _lock_payload(source):
    return {
        "token": str(uuid.uuid4()),
        "pid": os.getpid(),
        "source": source,
        "created_epoch": time.time(),
    }


def _read_lock(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return None
    except Exception:
        return {"created_epoch": 0, "corrupt": True}


def _is_stale_lock(path):
    data = _read_lock(path)
    if not data:
        return False
    try:
        created = float(data.get("created_epoch", 0))
    except (TypeError, ValueError):
        created = 0
    return (time.time() - created) > LOCK_STALE_SECONDS


@contextmanager
def active_trades_lock(source="system", wait_seconds=LOCK_WAIT_SECONDS):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = active_trades_lock_file()
    payload = _lock_payload(source)
    deadline = time.time() + wait_seconds
    acquired = False

    while time.time() <= deadline:
        fd = None
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                fd = None
                json.dump(payload, f)
            acquired = True
            break
        except FileExistsError:
            if _is_stale_lock(path):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
                continue
            time.sleep(LOCK_POLL_SECONDS)
        finally:
            if fd is not None:
                os.close(fd)

    if not acquired:
        raise ActiveTradeLockTimeout(f"Could not acquire active_trades lock within {wait_seconds:.1f}s")

    try:
        yield
    finally:
        current = _read_lock(path)
        if current and current.get("token") == payload["token"]:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def read_active_trades(strict=False):
    if not os.path.exists(config.ACTIVE_TRADES_FILE):
        return {}
    try:
        with open(config.ACTIVE_TRADES_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        if strict:
            raise ActiveTradeFileCorrupt("active_trades.json root is not an object")
        return {}
    except ActiveTradeFileCorrupt:
        raise
    except Exception as exc:
        if strict:
            raise ActiveTradeFileCorrupt(f"Could not read active trades: {exc}")
        return {}


def _write_active_trades(trades):
    temp_path = f"{config.ACTIVE_TRADES_FILE}.tmp"
    with open(temp_path, "w") as f:
        json.dump(trades, f, indent=4)
    os.replace(temp_path, config.ACTIVE_TRADES_FILE)


def load_trades(strict=False):
    return read_active_trades(strict=strict)


def ensure_store_ready(source="execution"):
    with active_trades_lock(source=source):
        return read_active_trades(strict=True)


def replace_trades(trades, source="system"):
    with active_trades_lock(source=source):
        read_active_trades(strict=True)
        safe_trades = trades if isinstance(trades, dict) else {}
        _write_active_trades(safe_trades)
        return safe_trades


def upsert_trade(symbol, trade, source="execution"):
    symbol = normalize_symbol(symbol)
    with active_trades_lock(source=source):
        trades = read_active_trades(strict=True)
        trades[symbol] = trade
        _write_active_trades(trades)
        return trades


def remove_trade(symbol, source="execution"):
    symbol = normalize_symbol(symbol)
    with active_trades_lock(source=source):
        trades = read_active_trades(strict=True)
        trades.pop(symbol, None)
        _write_active_trades(trades)
        return trades


def merge_trades(mutator, source="system"):
    with active_trades_lock(source=source):
        trades = read_active_trades(strict=True)
        result = mutator(trades)
        _write_active_trades(trades)
        return result if result is not None else trades
