"""
Shared helper functions used across multiple router modules.
Extracted from dashboard_app.py to avoid circular imports and duplication.
"""

import os
import json
import subprocess

import config


def is_process_running(script_name: str) -> bool:
    """
    Checks if a Python process with the given script name is running.
    Uses pgrep to locate the process identifier.
    """
    try:
        cmd = f"pgrep -f '{script_name}'"
        subprocess.check_output(cmd, shell=True)
        return True
    except subprocess.CalledProcessError:
        return False


def get_python_executable():
    """
    Returns the path to the workspace venv Python interpreter.
    """
    return os.path.join(config.BACKEND_DIR, "venv", "bin", "python")


def load_watchlist():
    """
    Reads the watchlist JSON file. If it doesn't exist, initializes it.
    """
    if not os.path.exists(config.WATCHLIST_FILE):
        watchlist = {"buy": [], "sell": []}
        try:
            with open(config.WATCHLIST_FILE, "w") as f:
                json.dump(watchlist, f, indent=4)
        except Exception as e:
            print(f"Error creating watchlist file: {e}")
        return watchlist
    try:
        with open(config.WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading watchlist: {e}")
        return {"buy": [], "sell": []}


def load_local_trades():
    """Reads persisted active trades from active_trades.json."""
    if os.path.exists(config.ACTIVE_TRADES_FILE):
        try:
            with open(config.ACTIVE_TRADES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_local_trades(trades):
    """Saves active trades atomically to active_trades.json."""
    try:
        temp_path = f"{config.ACTIVE_TRADES_FILE}.tmp"
        with open(temp_path, "w") as f:
            json.dump(trades, f, indent=4)
        os.replace(temp_path, config.ACTIVE_TRADES_FILE)
    except Exception as e:
        print(f"❌ Failed to save active trades: {e}")


def load_symbol_to_token():
    """Reads symbol to token mappings from cached file."""
    if os.path.exists(config.INSTRUMENT_MAPPING_FILE):
        try:
            with open(config.INSTRUMENT_MAPPING_FILE, "r") as f:
                mappings = json.load(f)
                return {k: int(v) for k, v in mappings.get("symbol_to_token", {}).items()}
        except Exception:
            pass
    return {}
