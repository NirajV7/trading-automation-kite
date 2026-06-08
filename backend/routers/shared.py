"""
Shared helper functions used across multiple router modules.
Extracted from dashboard_app.py to avoid circular imports and duplication.
"""

import os
import json
import subprocess

import config
from active_trade_store import ActiveTradeStoreError, load_trades, replace_trades


def get_process_command_lines(script_name: str) -> list:
    """
    Returns a list of full command line strings for all running Python processes
    that contain the given script_name.
    """
    command_lines = []
    if os.name == 'nt':
        try:
            cmd = 'wmic process where "name=\'python.exe\' or name=\'pythonw.exe\'" get commandline'
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode(errors='ignore')
            for line in output.splitlines():
                line_strip = line.strip()
                if script_name in line_strip and "wmic" not in line_strip:
                    command_lines.append(line_strip)
        except Exception:
            try:
                cmd = f'powershell -Command "Get-CimInstance Win32_Process -Filter \\"Name=\'python.exe\' or Name=\'pythonw.exe\'\\" | Select-Object -ExpandProperty CommandLine"'
                output = subprocess.check_output(cmd, shell=True).decode(errors='ignore')
                for line in output.splitlines():
                    line_strip = line.strip()
                    if line_strip and script_name in line_strip:
                        command_lines.append(line_strip)
            except Exception:
                pass
    else:
        try:
            cmd = "ps aux | grep python"
            output = subprocess.check_output(cmd, shell=True).decode(errors='ignore')
            for line in output.splitlines():
                if script_name in line and "grep" not in line:
                    command_lines.append(line)
        except Exception:
            pass
    return command_lines


def is_process_running(script_name: str) -> bool:
    """
    Checks if a Python process with the given script name is running.
    """
    return len(get_process_command_lines(script_name)) > 0


def get_python_executable():
    """
    Returns the path to the workspace venv Python interpreter.
    """
    if os.name == 'nt':
        return os.path.join(config.BACKEND_DIR, "venv", "Scripts", "python.exe")
    return os.path.join(config.BACKEND_DIR, "venv", "bin", "python")


def kill_process_by_name(script_name: str):
    """
    Terminates any Python process running the given script name.
    """
    if os.name == 'nt':
        try:
            cmd = 'wmic process where "name=\'python.exe\' or name=\'pythonw.exe\'" get processid,commandline'
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode(errors='ignore')
            killed_any = False
            for line in output.splitlines():
                line_strip = line.strip()
                if script_name in line_strip and "wmic" not in line_strip:
                    parts = line_strip.split()
                    if parts:
                        pid = parts[-1]
                        if pid.isdigit():
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True)
                            killed_any = True
            if killed_any:
                return
        except Exception:
            pass

        try:
            cmd = f'powershell -Command "Get-CimInstance Win32_Process -Filter \\"Name=\'python.exe\' or Name=\'pythonw.exe\'\\" | Where-Object {{$_.CommandLine -like \'*{script_name}*\'}} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"'
            subprocess.run(cmd, shell=True)
        except Exception:
            pass
    else:
        subprocess.run(f"pkill -f {script_name}", shell=True)


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
    return load_trades(strict=False)


def save_local_trades(trades):
    """Saves active trades using the shared cross-process lock."""
    try:
        return replace_trades(trades, source="router")
    except ActiveTradeStoreError as e:
        print(f"❌ Failed to save active trades: {e}")
        return None


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


LOGGER_STATE_FILE = os.path.join(config.DATA_DIR, "logger_state.json")

def is_logger_enabled() -> bool:
    """Checks if the logger is configured to be active (persisted state)."""
    if not os.path.exists(LOGGER_STATE_FILE):
        return True  # Default to True if file doesn't exist
    try:
        with open(LOGGER_STATE_FILE, "r") as f:
            data = json.load(f)
            return data.get("enabled", True)
    except Exception:
        return True


def set_logger_enabled(enabled: bool):
    """Persists the configured state of the logger."""
    try:
        with open(LOGGER_STATE_FILE, "w") as f:
            json.dump({"enabled": enabled}, f)
    except Exception as e:
        print(f"Error saving logger state: {e}")
