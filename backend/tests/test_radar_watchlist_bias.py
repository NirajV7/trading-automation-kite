import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import config
import radar_strategy
import symbol_cooldowns
import trade_journal


class DummyRadar(radar_strategy.RadarStrategyMixin):
    def __init__(self):
        self.active_trades = {}
        self.radar_candidates = {}
        self.logs = []

    def log_message(self, msg, is_error=False):
        self.logs.append((msg, is_error))

    def log_gate_failure(self, symbol, key, msg):
        self.logs.append((msg, False))

    def save_radar_candidates(self):
        pass


class FakeMarketDateTime:
    @classmethod
    def now(cls):
        class FakeNow:
            def time(self):
                return radar_strategy.datetime_time(10, 0, 0)

            def strftime(self, fmt):
                return "2026-05-29 10:00:00"

        return FakeNow()


class RadarWatchlistBiasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_watchlist = config.WATCHLIST_FILE
        self.old_journal = trade_journal.JOURNAL_FILE
        self.old_cooldowns = symbol_cooldowns.COOLDOWNS_FILE
        config.WATCHLIST_FILE = os.path.join(self.tmp.name, "watchlist.json")
        trade_journal.JOURNAL_FILE = os.path.join(self.tmp.name, "events.jsonl")
        symbol_cooldowns.COOLDOWNS_FILE = os.path.join(self.tmp.name, "cooldowns.json")
        with open(config.WATCHLIST_FILE, "w") as f:
            json.dump({"buy": ["JINDALSAW"], "sell": ["ONGC"], }, f)

    def tearDown(self):
        config.WATCHLIST_FILE = self.old_watchlist
        trade_journal.JOURNAL_FILE = self.old_journal
        symbol_cooldowns.COOLDOWNS_FILE = self.old_cooldowns
        self.tmp.cleanup()

    def metrics_for_spike(self, direction):
        return {
            "prev_open_1m": 100,
            "prev_close_1m": 101 if direction == "BUY" else 99,
            "prev_volume_1m": 400,
            "avg_vol_1m": 100,
        }

    def test_sell_watchlist_blocks_radar_buy(self):
        radar = DummyRadar()
        with patch.object(radar_strategy, "datetime", FakeMarketDateTime), patch.object(radar_strategy, "can_open_trade", return_value={"allowed": True}), patch.object(radar_strategy.config, "VOLUME_SPIKE_RATIO", 3.0), patch.object(radar_strategy.config, "PRICE_MOMENTUM_PCT", 0.25):
            radar.evaluate_radar_signals("ONGC", 101, self.metrics_for_spike("BUY"))

        self.assertNotIn("ONGC", radar.radar_candidates)
        events = trade_journal.read_events(symbol="ONGC")
        self.assertEqual(events[0]["reason"], "Watchlist bias SELL blocks Radar BUY")

    def test_neutral_symbol_allows_radar_direction(self):
        radar = DummyRadar()
        with patch.object(radar_strategy, "datetime", FakeMarketDateTime), patch.object(radar_strategy, "can_open_trade", return_value={"allowed": True}), patch.object(radar_strategy.config, "VOLUME_SPIKE_RATIO", 3.0), patch.object(radar_strategy.config, "PRICE_MOMENTUM_PCT", 0.25):
            radar.evaluate_radar_signals("RELIANCE", 101, self.metrics_for_spike("BUY"))

        self.assertEqual(radar.radar_candidates["RELIANCE"]["direction"], "BUY")


if __name__ == "__main__":
    unittest.main()
