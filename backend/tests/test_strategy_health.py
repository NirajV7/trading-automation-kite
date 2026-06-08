import os
import sys
import types
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

class FakeRouter:
    def get(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator


sys.modules.setdefault("fastapi", types.SimpleNamespace(APIRouter=lambda: FakeRouter(), Query=lambda default=None, **kwargs: default))
sys.modules.setdefault("fastapi.responses", types.SimpleNamespace(JSONResponse=lambda data: data))

from routers.trade_monitor import build_strategy_card


class StrategyHealthTests(unittest.TestCase):
    def test_closed_states_are_not_active(self):
        states = {
            "JINDALSAW": {"symbol": "JINDALSAW", "strategy": "RADAR", "direction": "BUY", "state": "CLOSED"},
            "ONGC": {"symbol": "ONGC", "strategy": "RADAR", "direction": "BUY", "state": "ACTIVE"},
        }

        card = build_strategy_card(
            "NIFTY_RADAR",
            "Nifty 50 Radar",
            events=[],
            states=states,
            cooldowns={},
            governor={"status": "ARMED"},
        )

        self.assertEqual(len(card["active_states"]), 1)
        self.assertEqual(card["active_states"][0]["symbol"], "ONGC")


if __name__ == "__main__":
    unittest.main()
