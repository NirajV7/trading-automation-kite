# Python Backend Service

Runs on Dell G15 Alienware (Home Server).

## Components
*   `config.py`: Local credentials and system parameters.
*   `kite_auth_manager.py`: Session caching and authentication.
*   `kite_data_logger.py`: Tick stream aggregator and indicator computer.
*   `kite_execution_core.py`: Strategy execution and sizing logic.
*   `dashboard_app.py`: FastAPI server for local network and Tailscale telemetry.
