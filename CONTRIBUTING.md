# Contributing

Contributions should preserve the project's first principle: capital protection before automation.

## Local Workflow

1. Keep live trading disabled unless you are intentionally testing with real capital.
2. Copy `backend/.env.example` to `backend/.env`.
3. Run backend tests before opening a pull request:

   ```bash
   python -m unittest discover backend/tests
   ```

4. Run frontend build before UI pull requests:

   ```bash
   cd frontend
   npm run build
   ```

## Pull Request Rules

- Default mode must remain dry-run.
- No secrets, tokens, trade logs, account data, or personal watchlists.
- Safety changes need clear tests.
- Broker-facing order changes must document failure modes.
- UI changes must keep live-mode warnings visible.

## Good First Areas

- demo data provider
- paper trading mode
- broker adapter interface
- risk-governor test coverage
- documentation screenshots
- backtesting/import tooling
