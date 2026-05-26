"""
Zerodha Authentication Handlers Router.
Handles: auth URL retrieval and OAuth callback token exchange.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from kite_auth_manager import check_kite_auth, exchange_kite_token
from routers.system import start_logger

router = APIRouter()


@router.get("/api/kite/auth_url")
def get_auth_url():
    """
    Exposes the Zerodha Kite redirect authorization URL.
    """
    needs_login, auth_url = check_kite_auth()
    return JSONResponse({"needs_login": needs_login, "auth_url": auth_url})


@router.get("/api/kite/callback")
@router.get("/kite_auth")
def kite_auth_callback(request_token: str = None):
    """
    Redirect endpoint for Zerodha authentication callback.
    Exchanges request_token for daily access token.
    """
    if not request_token:
        return JSONResponse({"status": "error", "message": "No request token provided"}, status_code=400)
        
    success, message = exchange_kite_token(request_token)
    if success:
        try:
            start_logger()
            message += " and background data logger started."
        except Exception as logger_err:
            message += f" (Logger start failed: {logger_err})"
        return JSONResponse({"status": "success", "message": message})
    return JSONResponse({"status": "error", "message": message}, status_code=500)
