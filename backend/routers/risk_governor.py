from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kite_auth_manager import check_kite_auth
from kite_telemetry import get_kite_positions
from risk_governor import get_status, manual_halt, reset_halt, reset_settings_to_defaults, update_settings
from routers.shared import load_local_trades

router = APIRouter()


@router.get("/api/risk-governor")
def api_risk_governor_status():
    needs_login, _ = check_kite_auth()
    positions = [] if needs_login else get_kite_positions()
    active_trades = load_local_trades()
    return JSONResponse(get_status(positions=positions, active_trades=active_trades, auth_needs_login=needs_login))


@router.put("/api/risk-governor/settings")
async def api_risk_governor_settings(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request payload"}, status_code=400)
    return JSONResponse(update_settings(data))


@router.post("/api/risk-governor/halt")
async def api_risk_governor_halt(request: Request):
    message = "Manual halt from Kill Switch UI"
    try:
        data = await request.json()
        message = data.get("message") or message
    except Exception:
        pass
    return JSONResponse(manual_halt(message))


@router.post("/api/risk-governor/reset")
def api_risk_governor_reset():
    return JSONResponse(reset_halt())


@router.post("/api/risk-governor/settings/defaults")
def api_risk_governor_settings_defaults():
    return JSONResponse(reset_settings_to_defaults())
