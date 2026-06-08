import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import execution_readiness


IST = ZoneInfo("Asia/Kolkata")


class ExecutionReadinessTests(unittest.TestCase):
    def assess(self, hour, minute, tick_age=None, orb_count=0):
        current = datetime(2026, 6, 2, hour, minute, tzinfo=IST)
        with patch.object(execution_readiness, "newest_live_tick_age_seconds", return_value=tick_age):
            return execution_readiness.assess_execution_readiness(
                orb_count=orb_count,
                snapshot={},
                current_time=current,
            )

    def test_premarket_waits_without_stale_block(self):
        status = self.assess(8, 30, tick_age=999, orb_count=0)

        self.assertFalse(status["ready"])
        self.assertFalse(status["orb_ready"])
        self.assertFalse(status["radar_ready"])
        self.assertEqual(status["status"], execution_readiness.WAITING_FOR_MARKET_OPEN)

    def test_warmup_blocks_all_strategies_before_orb_time(self):
        status = self.assess(9, 20, tick_age=1, orb_count=0)

        self.assertFalse(status["ready"])
        self.assertFalse(status["orb_ready"])
        self.assertFalse(status["radar_ready"])
        self.assertEqual(status["status"], execution_readiness.WARMING_UP)

    def test_after_orb_time_still_blocks_radar_until_935(self):
        status = self.assess(9, 31, tick_age=1, orb_count=0)

        self.assertFalse(status["ready"])
        self.assertFalse(status["orb_ready"])
        self.assertFalse(status["radar_ready"])
        self.assertEqual(status["status"], execution_readiness.ORB_BUILDING)

    def test_orb_ready_before_radar_confirmation_time(self):
        status = self.assess(9, 31, tick_age=1, orb_count=50)

        self.assertFalse(status["ready"])
        self.assertTrue(status["orb_ready"])
        self.assertFalse(status["radar_ready"])
        self.assertEqual(status["status"], execution_readiness.WARMING_UP)

    def test_after_radar_time_ready_with_fresh_ticks_and_ranges(self):
        status = self.assess(9, 35, tick_age=1, orb_count=50)

        self.assertTrue(status["ready"])
        self.assertTrue(status["orb_ready"])
        self.assertTrue(status["radar_ready"])
        self.assertEqual(status["status"], execution_readiness.READY)

    def test_stale_live_ticks_block_during_market(self):
        status = self.assess(9, 31, tick_age=20, orb_count=50)

        self.assertFalse(status["ready"])
        self.assertFalse(status["orb_ready"])
        self.assertFalse(status["radar_ready"])
        self.assertEqual(status["status"], execution_readiness.BLOCKED_STALE_DATA)


if __name__ == "__main__":
    unittest.main()
