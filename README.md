# Kite Quant Terminal

Risk-first desktop trading terminal for Zerodha Kite Connect.

This project combines a Python/FastAPI backend with a React/Electron dashboard for local trading automation research. It focuses on safety controls around execution: dry-run mode, risk governor, kill switch, order state tracking, stale market-data checks, trade journaling, and broker/local reconciliation.

> Trading risk warning: This software can route real orders only when explicitly configured. It is not investment advice. Use dry-run mode first, understand every order path, and trade only capital you can afford to lose.

## Features

- Zerodha Kite authentication and local session handling
- Dry-run execution mode by default
- Explicit live-trading gate via `KITE_ENABLE_LIVE_TRADING=true`
- Risk governor with halt reasons and dashboard controls
- Kill switch and square-off workflows
- Order state machine for entry, fill, stop-loss, and close tracking
- JSONL trade journal and strategy health endpoints
- Watchlist radar and technical chart dashboard
- Stale tick checks and broker/local mismatch protections

## Architecture

- `backend/`: FastAPI API, Kite Connect integration, execution engine, risk governor, trade journal, and tests
- `frontend/`: Vite + React + Electron terminal UI
- `backend/data/`: local runtime state such as tokens, watchlists, active trades, and market snapshots
- `backend/logs/`: local runtime logs

Runtime state files and secrets are ignored by git. Do not commit `.env`, tokens, logs, trade journals, active positions, or account-specific data.

## Safe Setup

1. Create backend environment file:

   ```bash
   cp backend/.env.example backend/.env
   ```

2. Fill Kite Connect credentials in `backend/.env`.

3. Keep live trading disabled until you have verified dry-run behavior:

   ```env
   KITE_ENABLE_LIVE_TRADING=false
   ```

4. Install frontend dependencies:

   ```bash
   cd frontend
   npm install
   npm run build
   ```

5. Run backend tests from repo root:

   ```bash
   python -m unittest discover backend/tests
   ```

## Live Trading Gate

Live order routing is disabled unless both conditions are true:

- Backend `.env` has `KITE_ENABLE_LIVE_TRADING=true`
- API request or CLI starts engine in `live` mode

Default behavior is dry-run simulation. This protects new users and contributors from accidental real-money execution.

## Open Source Status

This repository is being prepared for public OSS release under the MIT license. Maintainers should run a full secret scan before changing GitHub visibility.

## License

MIT. See `LICENSE`.
