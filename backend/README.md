# Python Backend Service

FastAPI backend for Kite authentication, market-data logging, dry-run execution,
risk controls, and dashboard APIs.

## Components

- `config.py`: Environment-backed settings and local runtime paths.
- `kite_auth_manager.py`: Kite Connect session handling.
- `kite_data_logger.py`: Tick stream aggregator and indicator computation.
- `kite_execution_core.py`: Strategy execution loop. Defaults to dry-run.
- `risk_governor.py`: Capital and safety halt checks.
- `order_state_machine.py`: Trade lifecycle tracking.
- `dashboard_app.py`: FastAPI server for the local terminal.

## Safety Defaults

Live order routing is disabled unless `KITE_ENABLE_LIVE_TRADING=true` exists in
`backend/.env`. Runtime state in `backend/data/` and logs in `backend/logs/` are
local-only and must not be committed.
