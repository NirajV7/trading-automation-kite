import os
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import kite_order_manager
import order_state_machine
import order_executor
import symbol_cooldowns
import trade_journal
from kite_data_logger import KiteDataLogger


class FakeKite:
    def __init__(self):
        self.placed = []
        self.modified = []
        self.cancelled = []
        self.order_states = {}
        self.net_qty = {}

    def place_order(self, **kwargs):
        self.placed.append(kwargs)
        order_id = f"ORDER{len(self.placed)}"
        self.order_states[order_id] = {
            "order_id": order_id,
            "status": "COMPLETE",
            "average_price": kwargs.get("price") or 100.0,
            "quantity": kwargs.get("quantity"),
            "filled_quantity": kwargs.get("quantity"),
            "tradingsymbol": kwargs.get("tradingsymbol"),
        }
        return order_id

    def modify_order(self, **kwargs):
        self.modified.append(kwargs)
        return kwargs["order_id"]

    def cancel_order(self, **kwargs):
        self.cancelled.append(kwargs)
        return kwargs["order_id"]

    def order_history(self, order_id):
        return [self.order_states[order_id]]

    def orders(self):
        return list(self.order_states.values())

    def positions(self):
        return {"net": []}


class DummyExecutor(order_executor.OrderExecutorMixin):
    def __init__(self):
        self.lock = threading.Lock()
        self.active_trades = {}
        self.cooldowns = {}
        self.dry_run = False
        self.logs = []

    def log_message(self, msg, is_error=False):
        self.logs.append((msg, is_error))

    def save_active_trades(self):
        pass


class ExecutionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state_file = order_state_machine.ORDER_STATES_FILE
        self.old_journal_file = trade_journal.JOURNAL_FILE
        self.old_cooldowns_file = symbol_cooldowns.COOLDOWNS_FILE
        order_state_machine.ORDER_STATES_FILE = os.path.join(self.tmp.name, "trade_states.json")
        trade_journal.JOURNAL_FILE = os.path.join(self.tmp.name, "trade_journal_events.jsonl")
        symbol_cooldowns.COOLDOWNS_FILE = os.path.join(self.tmp.name, "symbol_cooldowns.json")

    def tearDown(self):
        order_state_machine.ORDER_STATES_FILE = self.old_state_file
        trade_journal.JOURNAL_FILE = self.old_journal_file
        symbol_cooldowns.COOLDOWNS_FILE = self.old_cooldowns_file
        self.tmp.cleanup()

    def test_buffered_sl_prices_sell_and_buy(self):
        sell_trigger, sell_limit = kite_order_manager.get_buffered_sl_prices(1000, "SELL")
        buy_trigger, buy_limit = kite_order_manager.get_buffered_sl_prices(1000, "BUY")

        self.assertEqual(sell_trigger, 1000)
        self.assertLess(sell_limit, sell_trigger)
        self.assertEqual(buy_trigger, 1000)
        self.assertGreater(buy_limit, buy_trigger)

    def test_modify_or_place_sl_uses_buffered_limit(self):
        fake = FakeKite()
        with patch.object(kite_order_manager, "get_kite_client", return_value=fake):
            res = kite_order_manager.modify_or_place_sl(
                symbol="RELIANCE",
                new_trigger_price=1000,
                quantity=1,
                transaction_type="SELL",
                product="MIS",
            )

        self.assertEqual(res["status"], "success")
        placed = fake.placed[0]
        self.assertEqual(placed["order_type"], "SL")
        self.assertEqual(placed["trigger_price"], 1000)
        self.assertLess(placed["price"], placed["trigger_price"])

    def test_live_entry_creates_virtual_target_only_after_fill(self):
        fake = FakeKite()
        executor = DummyExecutor()

        with patch.object(order_executor, "can_open_trade", return_value={"allowed": True}), patch.object(
            order_executor, "get_kite_client", return_value=fake
        ), patch.object(
            order_executor, "modify_or_place_sl", return_value={"status": "success", "order_id": "SL1"}
        ):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertEqual(len(fake.placed), 1)
        self.assertEqual(fake.placed[0]["order_type"], "MARKET")
        self.assertEqual(executor.active_trades["RELIANCE"]["target"], 104)
        self.assertIsNone(executor.active_trades["RELIANCE"]["target_id"])
        self.assertEqual(executor.active_trades["RELIANCE"]["sl_id"], "SL1")

    def test_live_entry_rejection_creates_no_trade(self):
        fake = FakeKite()
        executor = DummyExecutor()

        def rejected_order(**kwargs):
            order_id = "ORDER1"
            fake.order_states[order_id] = {"order_id": order_id, "status": "REJECTED"}
            return order_id

        fake.place_order = rejected_order
        with patch.object(order_executor, "can_open_trade", return_value={"allowed": True}), patch.object(order_executor, "get_kite_client", return_value=fake):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertNotIn("RELIANCE", executor.active_trades)

    def test_governor_block_prevents_live_order(self):
        fake = FakeKite()
        executor = DummyExecutor()

        with patch.object(order_executor, "can_open_trade", return_value={"allowed": False, "message": "halted"}), patch.object(
            order_executor, "get_kite_client", return_value=fake
        ):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertEqual(fake.placed, [])
        self.assertNotIn("RELIANCE", executor.active_trades)

    def test_state_machine_blocks_duplicate_open_trade(self):
        self.assertTrue(order_state_machine.start_trade("RELIANCE", "ORB", "BUY", qty=1, price=100)["ok"])

        res = order_state_machine.start_trade("RELIANCE", "ORB", "BUY", qty=1, price=101)

        self.assertFalse(res["ok"])
        self.assertIn("already has open state", res["message"])

    def test_loss_exit_sets_cooldown_but_profit_exit_does_not(self):
        loss_item = symbol_cooldowns.apply_exit_cooldown("RELIANCE", "ORB", "Stop Loss Hit", -100)
        profit_item = symbol_cooldowns.apply_exit_cooldown("INFY", "ORB", "Target Hit", 100)

        self.assertIsNotNone(loss_item)
        self.assertEqual(loss_item["minutes"], 30)
        self.assertIsNone(profit_item)

    def test_logger_maps_kite_total_depth_fields(self):
        logger = KiteDataLogger()
        token = 12345
        symbol = "RELIANCE"
        logger.token_to_symbol[token] = symbol

        logger.process_tick({
            "instrument_token": token,
            "last_price": 100.0,
            "volume_traded": 1000,
            "total_buy_quantity": 250,
            "total_sell_quantity": 125,
            "ohlc": {"close": 99.0, "open": 99.5, "high": 101.0, "low": 98.5},
        })

        self.assertEqual(logger.live_state[symbol]["buy_quantity"], 250)
        self.assertEqual(logger.live_state[symbol]["sell_quantity"], 125)


if __name__ == "__main__":
    unittest.main()
