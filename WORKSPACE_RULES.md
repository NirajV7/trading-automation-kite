# Trading Automation Kite Workspace Rules

This document outlines the strict engineering rules and guardrails for this codebase.

---

## 1. Risk & Safety Guardrails
*   **Dry-Run Default**: The system must boot in dry-run/simulator mode by default. Real live execution must require explicit environment configuration flags.
*   **Unified Risk Sizing**: Quantity calculations must strictly enforce: `Quantity = Risk_Cap (₹2,500) / (Entry - StopLoss)`.
*   **Simultaneous Stop-Loss**: Never place an entry order without placing its corresponding Stop-Loss order in the same execution sequence.
*   **Emergency Kill Switch**: A dedicated function and endpoint must exist to instantly cancel all pending orders and exit all open positions.

---

## 2. Architectural & Code Integrity
*   **Strict Modularity**: Keep code modular. Do not merge core execution, data logging, indicators, and telemetry back together.
*   **Config Centralization**: No inline file paths or secrets. Centralize all configurations in `config.py` and retrieve credentials from `.env`.
*   **Thread Safety**: All reads/writes to live tick caches and deques must use local thread locks to prevent race conditions during heavy WebSocket traffic.
*   **Atomic Caching**: Any runtime dump (like `live_market_data.json`) must be written atomically (temp file write then rename) to prevent dashboard reads from hitting half-written files.
*   **Clear Commenting**: Whenever you write or refactor code, include proper, detailed comments explaining the logic so that Niraj (NJ) can easily read and understand the functionality.

---

## 3. Git Protocol
*   **Local Commits Only**: Stage and commit changes locally to track progress. Do NOT push to the remote repository (`origin`) unless explicitly instructed.
