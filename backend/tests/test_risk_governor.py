import csv
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
import risk_governor
import trade_journal


class RiskGovernorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_governor_file = risk_governor.RISK_GOVERNOR_FILE
        self.old_journal = config.TRADE_JOURNAL_CSV
        self.old_event_journal = trade_journal.JOURNAL_FILE
        self.old_live_data = config.LIVE_MARKET_DATA_FILE
        risk_governor.RISK_GOVERNOR_FILE = os.path.join(self.tmp.name, "risk_governor.json")
        config.TRADE_JOURNAL_CSV = os.path.join(self.tmp.name, "trade_journal.csv")
        trade_journal.JOURNAL_FILE = os.path.join(self.tmp.name, "trade_journal_events.jsonl")
        config.LIVE_MARKET_DATA_FILE = os.path.join(self.tmp.name, "live_market_data.json")

    def tearDown(self):
        risk_governor.RISK_GOVERNOR_FILE = self.old_governor_file
        config.TRADE_JOURNAL_CSV = self.old_journal
        trade_journal.JOURNAL_FILE = self.old_event_journal
        config.LIVE_MARKET_DATA_FILE = self.old_live_data
        self.tmp.cleanup()

    def write_journal(self, pnls):
        with open(config.TRADE_JOURNAL_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Symbol", "Direction", "EntryPrice", "ExitPrice", "Qty", "PnL_INR", "PnL_Pct", "Strategy", "Reason"])
            for idx, pnl in enumerate(pnls):
                writer.writerow([f"{risk_governor.today_key()} 10:0{idx}:00", "RELIANCE", "BUY", 100, 99, 1, pnl, -1, "ORB", "Test"])

    def test_daily_loss_breach_halts(self):
        self.write_journal([-2500])
        risk_governor.update_settings({"daily_loss_limit": 2000})

        status = risk_governor.get_status()

        self.assertEqual(status["status"], "HALTED")
        self.assertEqual(status["state"]["halt_reasons"][0]["code"], "DAILY_LOSS_LIMIT")

    def test_consecutive_losses_halt(self):
        self.write_journal([-100, -150])
        risk_governor.update_settings({"max_consecutive_losses": 2})

        status = risk_governor.get_status()

        self.assertEqual(status["status"], "HALTED")
        self.assertEqual(status["state"]["halt_reasons"][0]["code"], "CONSECUTIVE_LOSSES")

    def test_max_trades_per_day_halts(self):
        self.write_journal([100, -50, 25])
        risk_governor.update_settings({"max_trades_per_day": 3})

        status = risk_governor.get_status()

        self.assertEqual(status["status"], "HALTED")
        self.assertEqual(status["state"]["halt_reasons"][0]["code"], "MAX_TRADES_PER_DAY")

    def test_missing_sl_halts(self):
        status = risk_governor.get_status(active_trades={"RELIANCE": {"sl_unprotected": True}})

        self.assertEqual(status["status"], "HALTED")
        self.assertEqual(status["state"]["halt_reasons"][0]["code"], "MISSING_SL")

    def test_stale_market_data_halts_inside_market_window(self):
        with patch.object(risk_governor, "is_market_window", return_value=True):
            status = risk_governor.get_status()

        self.assertEqual(status["status"], "HALTED")
        self.assertEqual(status["state"]["halt_reasons"][0]["code"], "STALE_MARKET_DATA")

    def test_manual_halt_and_unhalt(self):
        halted = risk_governor.manual_halt("test halt")
        self.assertEqual(halted["status"], "HALTED")

        reset = risk_governor.reset_halt()
        self.assertEqual(reset["status"], "ARMED")
        self.assertEqual(reset["state"]["halt_reasons"], [])

    def test_disabled_governor_allows_entry(self):
        risk_governor.manual_halt("test halt")
        risk_governor.update_settings({"enabled": False})

        res = risk_governor.can_open_trade("RELIANCE", "ORB", active_trades={})

        self.assertTrue(res["allowed"])

    def test_symbol_loss_lockout_blocks_same_symbol(self):
        self.write_journal([-100])

        res = risk_governor.can_open_trade("RELIANCE", "ORB", active_trades={})

        self.assertFalse(res["allowed"])
        self.assertEqual(res["code"], "SYMBOL_LOSS_LOCKOUT")

    def test_jsonl_journal_drives_metrics(self):
        trade_journal.record_trade_close("RELIANCE", "BUY", 100, 97, 1, "ORB", "Stop Loss Hit")

        status = risk_governor.get_status()

        self.assertEqual(status["metrics"]["realized_pnl"], -3.0)
        self.assertEqual(status["metrics"]["trades_today"], 1)

    def test_bad_saved_settings_repair_to_defaults(self):
        with open(risk_governor.RISK_GOVERNOR_FILE, "w") as f:
            json.dump({
                "settings": {
                    "daily_loss_limit": 0,
                    "max_consecutive_losses": 0,
                    "max_trades_per_day": 0,
                    "max_open_positions": 0,
                    "stale_market_data_threshold_seconds": 0,
                },
                "state": {"halted": False, "halt_reasons": None},
            }, f)

        status = risk_governor.get_status(evaluate=False)

        self.assertEqual(status["settings"]["daily_loss_limit"], 2000.0)
        self.assertEqual(status["settings"]["max_consecutive_losses"], 2)
        self.assertEqual(status["settings"]["max_trades_per_day"], 5)
        self.assertEqual(status["settings"]["max_open_positions"], 3)
        self.assertEqual(status["settings"]["stale_market_data_threshold_seconds"], 15)
        self.assertEqual(status["state"]["halt_reasons"], [])

    def test_reset_settings_to_defaults(self):
        risk_governor.update_settings({"daily_loss_limit": 500, "max_trades_per_day": 1, "enabled": False})

        status = risk_governor.reset_settings_to_defaults()

        self.assertEqual(status["settings"]["daily_loss_limit"], 2000.0)
        self.assertEqual(status["settings"]["max_trades_per_day"], 5)
        self.assertTrue(status["settings"]["enabled"])


if __name__ == "__main__":
    unittest.main()
