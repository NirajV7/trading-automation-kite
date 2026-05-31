# Security Policy

## Supported Versions

Security fixes target the current `main` branch until tagged releases are published.

## Reporting a Vulnerability

Do not open public issues for secrets, order-routing bypasses, account leakage, or real-money execution risks.

Report privately to the maintainer through GitHub security advisories or direct maintainer contact. Include:

- affected commit or release
- reproduction steps
- expected impact
- whether live order routing can be triggered

## Secret Handling

Never commit:

- `backend/.env`
- Kite access tokens
- API keys or API secrets
- trade logs or broker account snapshots
- active trade state
- personal watchlists

If a secret is committed, revoke it immediately, then rewrite git history before public release.

## Trading Safety

Live trading must remain gated behind `KITE_ENABLE_LIVE_TRADING=true`. Pull requests that weaken dry-run defaults, kill switch behavior, stale-data checks, or order-state protections require extra review.
