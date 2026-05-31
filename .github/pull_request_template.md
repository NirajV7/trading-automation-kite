## Summary

## Safety Checklist

- [ ] Dry-run remains default
- [ ] No secrets, tokens, logs, active trades, or account data committed
- [ ] Live trading still requires `KITE_ENABLE_LIVE_TRADING=true`
- [ ] Order-routing changes include tests or manual verification notes

## Tests

- [ ] `python -m unittest discover backend/tests`
- [ ] `npm run build` from `frontend/`
