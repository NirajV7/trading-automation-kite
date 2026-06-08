"""
System & Core Process Controls Router.
Handles: status, logs, start/stop logger, start/stop engine, force_refresh.
"""

import os
import json
import shutil
import subprocess
from datetime import datetime
from collections import deque
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import config
from execution_readiness import assess_execution_readiness
from market_data_guard import read_live_market_snapshot
from kite_auth_manager import check_kite_auth
from kite_telemetry import get_kite_margin, get_kite_orders, get_kite_positions
from kite_utils import get_public_ip
from routers.shared import is_process_running, get_python_executable, set_logger_enabled, kill_process_by_name, get_process_command_lines

router = APIRouter()
LOG_FILES = ("engine.log", "ticker.log", "startup_backend.log", "startup_frontend.log")


def archive_active_logs(reason="manual"):
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    archive_dir = os.path.join(config.LOGS_DIR, "archive", stamp)
    os.makedirs(archive_dir, exist_ok=True)

    archived = []
    for name in LOG_FILES:
        src = os.path.join(config.LOGS_DIR, name)
        if os.path.exists(src) and os.path.getsize(src) > 0:
            shutil.move(src, os.path.join(archive_dir, name))
            archived.append(name)

    header = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] Fresh log started after archive ({reason}).\n"
    for name in ("engine.log", "ticker.log"):
        with open(os.path.join(config.LOGS_DIR, name), "w") as f:
            f.write(header)

    return {"archive_dir": archive_dir, "archived": archived}


def read_execution_status(engine_state):
    if engine_state != "stopped" and os.path.exists(config.EXECUTION_STATUS_FILE):
        try:
            with open(config.EXECUTION_STATUS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return assess_execution_readiness(
        dry_run=(engine_state == "dry"),
        orb_count=0,
        snapshot=read_live_market_snapshot(),
    )


@router.get("/api/status")
def api_status():
    """
    System status endpoint reporting connection and process states.
    Checks:
    - Data Logger status (KiteTicker WebSocket)
    - Execution Core status (Simulated or Live engine)
    - Zerodha Kite Auth status & margin balances
    - IP whitelist status for remote Tailscale validation
    """
    logger_running = is_process_running("run_data_logger.py")
    
    # Check if execution core is running
    engine_state = "stopped"
    command_lines = get_process_command_lines("kite_execution_core.py")
    if command_lines:
        # Check if "live" string is present in process arguments
        if any("live" in cmd.lower() for cmd in command_lines):
            engine_state = "live"
        else:
            engine_state = "dry"

    readiness = read_execution_status(engine_state)

    # Zerodha Auth checks
    needs_login, auth_url = check_kite_auth()
    margin_data = None
    if not needs_login:
        margin_data = get_kite_margin()

    # Network / Tailscale Check
    network_info = get_public_ip()

    return JSONResponse({
        "status": "success",
        "data_logger": "active" if logger_running else "stopped",
        "kite_engine": engine_state,
        "kite_needs_login": needs_login,
        "kite_auth_url": auth_url,
        "kite_margin": margin_data,
        "network": network_info,
        "execution_readiness": readiness,
    })


@router.get("/api/logs")
def api_logs():
    """
    Returns the last 30 lines of the shared system engine log.
    """
    if not os.path.exists(config.ENGINE_LOG):
        return JSONResponse({"logs": "Log file not found."})
        
    try:
        with open(config.ENGINE_LOG, "r") as f:
            last_lines = "".join(deque(f, maxlen=30))
            return JSONResponse({"logs": last_lines})
    except Exception as e:
        return JSONResponse({"logs": f"Error reading logs: {str(e)}"})


@router.post("/api/system/archive_logs")
def archive_logs():
    result = archive_active_logs(reason="api")
    return JSONResponse({"status": "success", **result})


@router.post("/api/system/start_logger")
def start_logger():
    """
    Launches the Zerodha Kite Data Logger process in the background.
    """
    set_logger_enabled(True)
    if is_process_running("run_data_logger.py"):
        return JSONResponse({"status": "error", "message": "Data Logger is already running."})
        
    venv_py = get_python_executable()
    script_path = os.path.join(config.BACKEND_DIR, "run_data_logger.py")
    
    with open(config.ENGINE_LOG, "a") as log_file:
        subprocess.Popen(
            [venv_py, "-u", script_path],
            cwd=config.BACKEND_DIR,
            stdout=log_file,
            stderr=log_file
        )
    return JSONResponse({"status": "success", "message": "Kite Data Logger engine started."})


@router.post("/api/system/stop_logger")
def stop_logger():
    """
    Terminates the background Kite Data Logger process.
    """
    set_logger_enabled(False)
    if not is_process_running("run_data_logger.py"):
        return JSONResponse({"status": "error", "message": "Data Logger is already stopped."})
        
    kill_process_by_name("run_data_logger.py")
    return JSONResponse({"status": "success", "message": "Kite Data Logger engine stopped."})


@router.post("/api/system/force_refresh")
def force_refresh():
    """
    Force-refreshes all cached data:
    - Busts the positions cache (forces fresh Zerodha API call)
    - Busts the orders cache
    - Restarts the data logger if it crashed (fixes stuck LTP)
    """
    actions = []
    
    # 1. Force-refresh positions cache
    try:
        get_kite_positions(force=True)
        actions.append("Positions cache busted")
    except Exception as e:
        actions.append(f"Positions refresh failed: {e}")
    
    # 2. Force-refresh orders cache
    try:
        get_kite_orders()
        actions.append("Orders refreshed")
    except Exception as e:
        actions.append(f"Orders refresh failed: {e}")
    
    # 3. Auto-recover data logger if dead (fixes stuck LTP)
    logger_restarted = False
    if not is_process_running("run_data_logger.py"):
        try:
            set_logger_enabled(True)
            venv_py = get_python_executable()
            script_path = os.path.join(config.BACKEND_DIR, "run_data_logger.py")
            with open(config.ENGINE_LOG, "a") as log_file:
                subprocess.Popen(
                    [venv_py, "-u", script_path],
                    cwd=config.BACKEND_DIR,
                    stdout=log_file,
                    stderr=log_file
                )
            logger_restarted = True
            actions.append("Data Logger was dead — auto-restarted")
        except Exception as e:
            actions.append(f"Data Logger restart failed: {e}")
    else:
        actions.append("Data Logger already running")
    
    return JSONResponse({
        "status": "success", 
        "message": " | ".join(actions),
        "logger_restarted": logger_restarted
    })


@router.post("/api/system/start_engine")
async def start_engine(request: Request):
    """
    Launches the Kite Execution Core strategy engine.
    Supports payload parameter:
    - mode: "dry" (default simulator) or "live" (real capital execution)
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
        
    mode = data.get("mode", "dry").lower()
    if is_process_running("kite_execution_core.py"):
        return JSONResponse({"status": "error", "message": "Execution Core is already running."})
        
    venv_py = get_python_executable()
    script_path = os.path.join(config.BACKEND_DIR, "kite_execution_core.py")
    
    cmd = [venv_py, "-u", script_path]
    # Default execution is dry run; only pass 'live' explicitly if selected
    if mode == "live":
        cmd.append("live")
        
    with open(config.ENGINE_LOG, "a") as log_file:
        subprocess.Popen(
            cmd,
            cwd=config.BACKEND_DIR,
            stdout=log_file,
            stderr=log_file
        )
        
    mode_str = "LIVE REAL-MONEY" if mode == "live" else "DRY-RUN SIMULATION"
    return JSONResponse({"status": "success", "message": f"Kite Execution Core started in {mode_str} mode."})


@router.post("/api/system/stop_engine")
def stop_engine():
    """
    Terminates the background strategy execution engine process.
    """
    if not is_process_running("kite_execution_core.py"):
        return JSONResponse({"status": "error", "message": "Kite Execution Core is already stopped."})
        
    kill_process_by_name("kite_execution_core.py")
    return JSONResponse({"status": "success", "message": "Kite Execution Core stopped."})


@router.post("/api/system/start_all")
def start_all():
    """
    Convenience method to spin up both components (Logger & Dry-Run Engine).
    """
    logger_started = False
    engine_started = False
    
    venv_py = get_python_executable()
    
    if not is_process_running("run_data_logger.py"):
        script_logger = os.path.join(config.BACKEND_DIR, "run_data_logger.py")
        with open(config.ENGINE_LOG, "a") as log_file:
            subprocess.Popen([venv_py, "-u", script_logger], cwd=config.BACKEND_DIR, stdout=log_file, stderr=log_file)
        logger_started = True
            
    if not is_process_running("kite_execution_core.py"):
        script_engine = os.path.join(config.BACKEND_DIR, "kite_execution_core.py")
        with open(config.ENGINE_LOG, "a") as log_file:
            subprocess.Popen([venv_py, "-u", script_engine], cwd=config.BACKEND_DIR, stdout=log_file, stderr=log_file)
        engine_started = True
        
    return JSONResponse({
        "status": "success", 
        "message": f"Startup executed. Logger started: {logger_started}, Engine started: {engine_started}"
    })


@router.post("/api/system/stop_all")
def stop_all():
    """
    Convenience method to stop all trading engines.
    """
    set_logger_enabled(False)
    kill_process_by_name("run_data_logger.py")
    kill_process_by_name("kite_execution_core.py")
    return JSONResponse({
        "status": "success",
        "message": "All background processes terminated successfully."
    })
