"""
Kite Quant Terminal — API Backend Entrypoint.
Thin entrypoint that mounts all router modules and launches background daemons.
"""

import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from kite_auth_manager import check_kite_auth
from routers import system, kite_auth, watchlist, positions, orders
from safety_guardian import run_always_on_safety_guardian

# Initialize FastAPI App
app = FastAPI(title="Kite Quant Terminal API Backend", version="2.0.0")

# Enable CORS for frontend integration (Electron app or web interface)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all router modules
app.include_router(system.router)
app.include_router(kite_auth.router)
app.include_router(watchlist.router)
app.include_router(positions.router)
app.include_router(orders.router)


@app.on_event("startup")
def startup_event():
    """
    Launches background long-polling listener for interactive Telegram Bot controls.
    """
    try:
        from telegram_bot import start_telegram_polling
        start_telegram_polling()
        print("🤖 [Telegram] Background polling thread launched successfully.")
        
        # Auto-launch the WebSocket Data Logger on boot if daily access token is valid
        needs_login, _ = check_kite_auth()
        if not needs_login:
            system.start_logger()
            print("📈 [Logger] Auto-started background run_data_logger.py successfully.")
            
        # Launch Always-On Safety Guardian thread
        threading.Thread(target=run_always_on_safety_guardian, daemon=True).start()
        print("🛡️ [Safety Guardian] Background safety thread launched successfully.")
    except Exception as e:
        print(f"❌ [Startup] Failed during automatic process launching: {e}")


# -------------------------------------------------------------
# MAIN APP EXECUTION
# -------------------------------------------------------------
if __name__ == "__main__":
    # Host on 0.0.0.0 (Tailscale mesh VPN compatibility)
    # Port 8080 as requested in the system architecture
    uvicorn.run("dashboard_app:app", host="0.0.0.0", port=8080, reload=True)
