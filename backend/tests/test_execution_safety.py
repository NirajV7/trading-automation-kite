import json
import os
import sys
import time
import threading
import tempfile
import types
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

sys.modules.setdefault("kiteconnect", types.SimpleNamespace(KiteConnect=object))

import config
import active_trade_store
import kite_order_manager
import market_data_guard
import order_state_machine
import order_executor
import position_monitor
import symbol_cooldowns
import trade_journal
import temporary_trade_controls
from kite_data_logger import KiteDataLogger


class FakeKite:
    def __init__(self):
        self.placed = []
        self.modified = []
        self.cancelled = []
        self.order_states = {}
        self.net_qty = {}
        self.positions_net = []

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
        return {"net": self.positions_net}


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


class DummyPositionMonitor(position_monitor.PositionMonitorMixin):
    def __init__(self):
        self.active_trades = {
            "RELIANCE": {
                "entry": 100,
                "qty": 1,
                "direction": "BUY",
                "sl": 98,
                "target": 104,
                "strategy": "ORB",
                "sl_id": "SL1",
            }
        }
        self.dry_run = False
        self.logs = []
        self.kite = None

    def log_message(self, msg, is_error=False):
        self.logs.append((msg, is_error))

    def save_active_trades(self):
        pass

    def close_active_trade_record(self, symbol, exit_price, reason, **kwargs):
        self.active_trades.pop(symbol, None)


class ExecutionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state_file = order_state_machine.ORDER_STATES_FILE
        self.old_journal_file = trade_journal.JOURNAL_FILE
        self.old_cooldowns_file = symbol_cooldowns.COOLDOWNS_FILE
        self.old_live_market_data_file = config.LIVE_MARKET_DATA_FILE
        self.old_active_trades_file = config.ACTIVE_TRADES_FILE
        self.old_exit_locks_dir = order_state_machine.EXIT_LOCKS_DIR
        self.old_temp_profit_enabled = config.TEMPORARY_PROFIT_BOOKING_ENABLED
        self.old_temp_profit_min_pnl = config.TEMPORARY_PROFIT_BOOKING_MIN_PNL
        self.old_temp_sl_enabled = config.TEMPORARY_SL_LOSS_CAP_ENABLED
        self.old_temp_sl_cap = config.TEMPORARY_SL_LOSS_CAP
        order_state_machine.ORDER_STATES_FILE = os.path.join(self.tmp.name, "trade_states.json")
        order_state_machine.EXIT_LOCKS_DIR = os.path.join(self.tmp.name, "exit_locks")
        config.LIVE_MARKET_DATA_FILE = os.path.join(self.tmp.name, "live_market_data.json")
        config.ACTIVE_TRADES_FILE = os.path.join(self.tmp.name, "active_trades.json")
        trade_journal.JOURNAL_FILE = os.path.join(self.tmp.name, "trade_journal_events.jsonl")
        symbol_cooldowns.COOLDOWNS_FILE = os.path.join(self.tmp.name, "symbol_cooldowns.json")
        config.TEMPORARY_PROFIT_BOOKING_ENABLED = True
        config.TEMPORARY_PROFIT_BOOKING_MIN_PNL = 500.0
        config.TEMPORARY_SL_LOSS_CAP_ENABLED = True
        config.TEMPORARY_SL_LOSS_CAP = 500.0

    def tearDown(self):
        order_state_machine.ORDER_STATES_FILE = self.old_state_file
        order_state_machine.EXIT_LOCKS_DIR = self.old_exit_locks_dir
        config.LIVE_MARKET_DATA_FILE = self.old_live_market_data_file
        config.ACTIVE_TRADES_FILE = self.old_active_trades_file
        trade_journal.JOURNAL_FILE = self.old_journal_file
        symbol_cooldowns.COOLDOWNS_FILE = self.old_cooldowns_file
        config.TEMPORARY_PROFIT_BOOKING_ENABLED = self.old_temp_profit_enabled
        config.TEMPORARY_PROFIT_BOOKING_MIN_PNL = self.old_temp_profit_min_pnl
        config.TEMPORARY_SL_LOSS_CAP_ENABLED = self.old_temp_sl_enabled
        config.TEMPORARY_SL_LOSS_CAP = self.old_temp_sl_cap
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

    def test_temporary_sl_cap_keeps_qty_sizing_but_places_500_loss_sl(self):
        fake = FakeKite()
        executor = DummyExecutor()
        qty = executor.calculate_position_size("RELIANCE", 100, 95)

        with patch.object(order_executor, "can_open_trade", return_value={"allowed": True}), patch.object(
            order_executor, "get_kite_client", return_value=fake
        ), patch.object(
            order_executor, "modify_or_place_sl", return_value={"status": "success", "order_id": "SL1"}
        ) as mocked_sl:
            executor.execute_live_order_placement("RELIANCE", "BUY", qty, 100, 95, 110, "ORB")

        self.assertEqual(qty, 200)
        self.assertEqual(mocked_sl.call_args.kwargs["new_trigger_price"], 97.5)
        self.assertEqual(executor.active_trades["RELIANCE"]["sl"], 97.5)
        self.assertEqual(order_state_machine.get_trade_state("RELIANCE")["sl"], 97.5)

    def test_temporary_sl_cap_sell_side(self):
        fake = FakeKite()
        executor = DummyExecutor()

        with patch.object(order_executor, "can_open_trade", return_value={"allowed": True}), patch.object(
            order_executor, "get_kite_client", return_value=fake
        ), patch.object(
            order_executor, "modify_or_place_sl", return_value={"status": "success", "order_id": "SL1"}
        ) as mocked_sl:
            executor.execute_live_order_placement("RELIANCE", "SELL", 200, 100, 105, 90, "ORB")

        self.assertEqual(mocked_sl.call_args.kwargs["new_trigger_price"], 102.5)
        self.assertEqual(executor.active_trades["RELIANCE"]["sl"], 102.5)

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

    def test_begin_exit_allows_one_exit_per_symbol(self):
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104)

        first = order_state_machine.begin_exit("RELIANCE", "Virtual target hit", "test", price=104)
        second = order_state_machine.begin_exit("RELIANCE", "Virtual target hit", "test", price=104)

        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertIn("exit already requested", second["message"])

    def test_stale_exit_lock_allows_retry(self):
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104)
        self.assertTrue(order_state_machine.begin_exit("RELIANCE", "Virtual target hit", "test", price=104)["ok"])
        lock_path = order_state_machine.exit_lock_path("RELIANCE")
        with open(lock_path, "w") as f:
            f.write('{"symbol": "RELIANCE", "created_epoch": 1}')

        retry = order_state_machine.begin_exit("RELIANCE", "Virtual target retry", "test", price=104, ttl_seconds=1)

        self.assertTrue(retry["ok"])

    def test_finish_exit_releases_lock_on_success_and_failure(self):
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104)
        self.assertTrue(order_state_machine.begin_exit("RELIANCE", "Virtual target hit", "test", price=104)["ok"])
        self.assertTrue(os.path.exists(order_state_machine.exit_lock_path("RELIANCE")))

        res = order_state_machine.finish_exit("RELIANCE", True, "Virtual target exit confirmed", "test", price=104, order_id="EXIT1")

        self.assertTrue(res["ok"])
        self.assertFalse(os.path.exists(order_state_machine.exit_lock_path("RELIANCE")))
        self.assertEqual(order_state_machine.get_trade_state("RELIANCE")["state"], "EXIT_FILLED")

        order_state_machine.reconcile_trade("INFY", "BUY", 1, 100, 98, 104)
        self.assertTrue(order_state_machine.begin_exit("INFY", "Virtual target hit", "test", price=104)["ok"])
        res = order_state_machine.finish_exit("INFY", False, "Exit failed", "test", price=104)

        self.assertTrue(res["ok"])
        self.assertFalse(os.path.exists(order_state_machine.exit_lock_path("INFY")))
        self.assertEqual(order_state_machine.get_trade_state("INFY")["state"], "EXIT_FAILED")

    def test_position_monitor_skips_when_exit_already_in_progress(self):
        self.write_live_data_file(stale=False)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104, strategy="ORB")
        first = order_state_machine.begin_exit("RELIANCE", "Virtual target hit", "safety_guardian", price=104)
        monitor = DummyPositionMonitor()

        with patch.object(position_monitor, "exit_single_position") as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 105, {"adr_absolute": 0})

        self.assertTrue(first["ok"])
        mocked_exit.assert_not_called()
        self.assertIn("Exit already in progress", monitor.logs[-1][0])

    def test_position_monitor_target_exit_calls_exit_once(self):
        self.write_live_data_file(stale=False)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104, strategy="ORB")
        monitor = DummyPositionMonitor()

        with patch.object(position_monitor, "exit_single_position", return_value={"status": "success", "exit_price": 104.5, "realized_pnl": 4.5, "order_id": "EXIT1"}) as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 105, {"adr_absolute": 0})
            monitor.active_trades["RELIANCE"] = {"entry": 100, "qty": 1, "direction": "BUY", "sl": 98, "target": 104, "strategy": "ORB", "sl_id": "SL1"}
            monitor.process_live_price_update("RELIANCE", 105, {"adr_absolute": 0})

        self.assertEqual(mocked_exit.call_count, 1)

    def write_live_data_file(self, stale=False, symbol="RELIANCE", ltp=105):
        tick_epoch = time.time() - (120 if stale else 0)
        with open(config.LIVE_MARKET_DATA_FILE, "w") as f:
            json.dump({symbol: {"ltp": ltp, "tick_epoch": tick_epoch, "tick_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(tick_epoch))}}, f)

    def test_temporary_profit_booking_buy_exits_at_500_pnl(self):
        self.write_live_data_file(stale=False)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 200, 100, 97.5, 150, strategy="ORB")
        monitor = DummyPositionMonitor()
        monitor.active_trades["RELIANCE"] = {"entry": 100, "qty": 200, "direction": "BUY", "sl": 97.5, "target": 150, "strategy": "ORB", "sl_id": "SL1"}

        with patch.object(position_monitor, "exit_single_position", return_value={"status": "success", "exit_price": 102.5, "realized_pnl": 500, "order_id": "EXIT1"}) as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 102.5, {"adr_absolute": 0})

        mocked_exit.assert_called_once()
        self.assertNotIn("RELIANCE", monitor.active_trades)

    def test_temporary_profit_booking_sell_exits_at_500_pnl(self):
        self.write_live_data_file(stale=False)
        order_state_machine.reconcile_trade("RELIANCE", "SELL", 200, 100, 102.5, 90, strategy="ORB")
        monitor = DummyPositionMonitor()
        monitor.active_trades["RELIANCE"] = {"entry": 100, "qty": 200, "direction": "SELL", "sl": 102.5, "target": 90, "strategy": "ORB", "sl_id": "SL1"}

        with patch.object(position_monitor, "exit_single_position", return_value={"status": "success", "exit_price": 97.5, "realized_pnl": 500, "order_id": "EXIT1"}) as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 97.5, {"adr_absolute": 0})

        mocked_exit.assert_called_once()

    def test_stale_cache_temporary_profit_skips_when_kite_ltp_disagrees(self):
        self.write_live_data_file(stale=True)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 200, 100, 97.5, 150, strategy="ORB")
        monitor = DummyPositionMonitor()
        monitor.active_trades["RELIANCE"] = {"entry": 100, "qty": 200, "direction": "BUY", "sl": 97.5, "target": 150, "strategy": "ORB", "sl_id": "SL1"}

        with patch.object(temporary_trade_controls, "get_kite_ltp", return_value=101), patch.object(position_monitor, "exit_single_position") as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 102.5, {"adr_absolute": 0})

        mocked_exit.assert_not_called()
        self.assertFalse(os.path.exists(order_state_machine.exit_lock_path("RELIANCE")))
        self.assertIn("Exit skipped: stale cache not confirmed", monitor.logs[-1][0])

    def test_stale_cache_temporary_profit_proceeds_when_kite_ltp_confirms(self):
        self.write_live_data_file(stale=True)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 200, 100, 97.5, 150, strategy="ORB")
        monitor = DummyPositionMonitor()
        monitor.active_trades["RELIANCE"] = {"entry": 100, "qty": 200, "direction": "BUY", "sl": 97.5, "target": 150, "strategy": "ORB", "sl_id": "SL1"}

        with patch.object(temporary_trade_controls, "get_kite_ltp", return_value=102.5), patch.object(position_monitor, "exit_single_position", return_value={"status": "success", "exit_price": 102.5, "realized_pnl": 500, "order_id": "EXIT1"}) as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 102.5, {"adr_absolute": 0})

        mocked_exit.assert_called_once()

    def test_temporary_profit_booking_respects_existing_exit_gate(self):
        self.write_live_data_file(stale=False)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 200, 100, 97.5, 150, strategy="ORB")
        first = order_state_machine.begin_exit("RELIANCE", "Temporary Profit Booking ₹500", "safety_guardian", price=102.5)
        monitor = DummyPositionMonitor()
        monitor.active_trades["RELIANCE"] = {"entry": 100, "qty": 200, "direction": "BUY", "sl": 97.5, "target": 150, "strategy": "ORB", "sl_id": "SL1"}

        with patch.object(position_monitor, "exit_single_position") as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 102.5, {"adr_absolute": 0})

        self.assertTrue(first["ok"])
        mocked_exit.assert_not_called()

    def test_fresh_cache_target_exit_does_not_fetch_kite_ltp(self):
        self.write_live_data_file(stale=False)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104, strategy="ORB")
        monitor = DummyPositionMonitor()

        with patch.object(market_data_guard, "get_kite_ltp") as mocked_ltp, patch.object(position_monitor, "exit_single_position", return_value={"status": "success", "exit_price": 104.5, "realized_pnl": 4.5, "order_id": "EXIT1"}) as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 105, {"adr_absolute": 0})

        mocked_ltp.assert_not_called()
        mocked_exit.assert_called_once()

    def test_stale_cache_target_exit_skips_when_kite_ltp_disagrees(self):
        self.write_live_data_file(stale=True)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104, strategy="ORB")
        monitor = DummyPositionMonitor()

        with patch.object(market_data_guard, "get_kite_ltp", return_value=103), patch.object(position_monitor, "exit_single_position") as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 105, {"adr_absolute": 0})

        mocked_exit.assert_not_called()
        self.assertFalse(os.path.exists(order_state_machine.exit_lock_path("RELIANCE")))
        self.assertIn("Exit skipped: stale cache not confirmed", monitor.logs[-1][0])

    def test_stale_cache_target_exit_proceeds_when_kite_ltp_confirms(self):
        self.write_live_data_file(stale=True)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104, strategy="ORB")
        monitor = DummyPositionMonitor()

        with patch.object(market_data_guard, "get_kite_ltp", return_value=105), patch.object(position_monitor, "exit_single_position", return_value={"status": "success", "exit_price": 104.8, "realized_pnl": 4.8, "order_id": "EXIT1"}) as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 105, {"adr_absolute": 0})

        mocked_exit.assert_called_once()

    def test_stale_cache_sl_fallback_skips_when_kite_ltp_disagrees(self):
        self.write_live_data_file(stale=True)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104, strategy="ORB")
        monitor = DummyPositionMonitor()
        fake = FakeKite()
        fake.order_states["SL1"] = {"order_id": "SL1", "status": "OPEN"}
        monitor.kite = fake

        with patch.object(market_data_guard, "get_kite_ltp", return_value=99), patch.object(position_monitor, "exit_single_position") as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 97, {"adr_absolute": 0})

        mocked_exit.assert_not_called()
        self.assertFalse(os.path.exists(order_state_machine.exit_lock_path("RELIANCE")))
        self.assertIn("Exit skipped: stale cache not confirmed", monitor.logs[-1][0])

    def test_kite_ltp_failure_skips_exit_and_lock(self):
        self.write_live_data_file(stale=True)
        order_state_machine.reconcile_trade("RELIANCE", "BUY", 1, 100, 98, 104, strategy="ORB")
        monitor = DummyPositionMonitor()

        with patch.object(market_data_guard, "get_kite_ltp", side_effect=RuntimeError("ltp down")), patch.object(position_monitor, "exit_single_position") as mocked_exit:
            monitor.process_live_price_update("RELIANCE", 105, {"adr_absolute": 0})

        mocked_exit.assert_not_called()
        self.assertFalse(os.path.exists(order_state_machine.exit_lock_path("RELIANCE")))
        self.assertIn("Exit skipped: stale cache not confirmed", monitor.logs[-1][0])


    def test_fresh_file_mtime_with_old_symbol_tick_is_stale(self):
        self.write_live_data_file(stale=True)

        stale, age, _ = market_data_guard.is_symbol_live_data_stale("RELIANCE")

        self.assertTrue(stale)
        self.assertGreaterEqual(age, 100)

    def test_active_trade_locked_merge_preserves_new_engine_trade(self):
        active_trade_store.upsert_trade("RELIANCE", {"entry": 100, "qty": 1, "direction": "BUY", "sl": 98, "target": 104}, source="test")
        stale_snapshot = active_trade_store.load_trades(strict=True)
        active_trade_store.upsert_trade("INFY", {"entry": 1500, "qty": 1, "direction": "BUY", "sl": 1490, "target": 1520}, source="engine")

        def guardian_merge(latest):
            latest["RELIANCE"] = stale_snapshot["RELIANCE"]
            latest["RELIANCE"]["sl"] = 99

        active_trade_store.merge_trades(guardian_merge, source="guardian")
        final = active_trade_store.load_trades(strict=True)

        self.assertIn("INFY", final)
        self.assertEqual(final["RELIANCE"]["sl"], 99)

    def test_stale_active_trade_lock_allows_retry(self):
        with open(active_trade_store.active_trades_lock_file(), "w") as f:
            json.dump({"token": "old", "created_epoch": time.time() - 30}, f)

        active_trade_store.upsert_trade("RELIANCE", {"entry": 100}, source="test")

        self.assertIn("RELIANCE", active_trade_store.load_trades(strict=True))

    def test_active_trade_lock_contention_blocks_live_entry(self):
        fake = FakeKite()
        executor = DummyExecutor()
        with open(active_trade_store.active_trades_lock_file(), "w") as f:
            json.dump({"token": "fresh", "created_epoch": time.time()}, f)

        with patch.object(order_executor, "get_kite_client", return_value=fake):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertEqual(fake.placed, [])

    def test_corrupt_active_trades_blocks_live_entry(self):
        fake = FakeKite()
        executor = DummyExecutor()
        with open(config.ACTIVE_TRADES_FILE, "w") as f:
            f.write("{")

        with patch.object(order_executor, "get_kite_client", return_value=fake):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertEqual(fake.placed, [])

    def test_broker_existing_position_blocks_live_entry(self):
        fake = FakeKite()
        fake.positions_net = [{"tradingsymbol": "RELIANCE", "quantity": 1, "average_price": 100}]
        executor = DummyExecutor()

        with patch.object(order_executor, "get_kite_client", return_value=fake):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertEqual(fake.placed, [])

    def test_broker_position_fetch_failure_blocks_live_entry(self):
        fake = FakeKite()
        executor = DummyExecutor()

        def fail_positions():
            raise RuntimeError("positions down")

        fake.positions = fail_positions
        with patch.object(order_executor, "get_kite_client", return_value=fake):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertEqual(fake.placed, [])

    def test_entry_timeout_with_broker_position_recovers_trade_and_sl(self):
        fake = FakeKite()
        executor = DummyExecutor()
        calls = {"count": 0}

        def positions_after_timeout():
            calls["count"] += 1
            if calls["count"] <= 2:
                return {"net": []}
            return {"net": [{"tradingsymbol": "RELIANCE", "quantity": 200, "average_price": 100.5}]}

        fake.positions = positions_after_timeout
        with patch.object(order_executor, "can_open_trade", return_value={"allowed": True}), patch.object(
            order_executor, "get_kite_client", return_value=fake
        ), patch.object(
            order_executor, "wait_for_order_completion", return_value={"status": "timeout", "order": {"status": "OPEN"}}
        ), patch.object(
            order_executor, "modify_or_place_sl", return_value={"status": "success", "order_id": "SL1"}
        ):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertEqual(len(fake.placed), 1)
        self.assertEqual(executor.active_trades["RELIANCE"]["qty"], 200)
        self.assertEqual(executor.active_trades["RELIANCE"]["sl_id"], "SL1")

    def test_entry_timeout_broker_check_failure_halts_unknown_status(self):
        fake = FakeKite()
        executor = DummyExecutor()
        calls = {"count": 0}

        def positions_then_fail():
            calls["count"] += 1
            if calls["count"] <= 2:
                return {"net": []}
            raise RuntimeError("positions down")

        fake.positions = positions_then_fail
        with patch.object(order_executor, "can_open_trade", return_value={"allowed": True}), patch.object(
            order_executor, "get_kite_client", return_value=fake
        ), patch.object(
            order_executor, "wait_for_order_completion", return_value={"status": "timeout", "order": {"status": "OPEN"}}
        ):
            executor.execute_live_order_placement("RELIANCE", "BUY", 1, 100, 98, 104, "ORB")

        self.assertNotIn("RELIANCE", executor.active_trades)
        self.assertEqual(order_state_machine.get_trade_state("RELIANCE")["state"], "ENTRY_TIMEOUT")

    def test_loss_exit_sets_cooldown_but_profit_exit_does_not(self):
        loss_item = symbol_cooldowns.apply_exit_cooldown("RELIANCE", "ORB", "Stop Loss Hit", -100)
        profit_item = symbol_cooldowns.apply_exit_cooldown("INFY", "ORB", "Target Hit", 100)

        self.assertIsNotNone(loss_item)
        self.assertEqual(loss_item["minutes"], 30)
        self.assertIsNone(profit_item)

    def test_duplicate_blocked_events_are_deduped(self):
        trade_journal.append_event("SIGNAL_BLOCKED", symbol="RELIANCE", strategy="RADAR", state="BLOCKED", reason="cooldown")
        trade_journal.append_event("SIGNAL_BLOCKED", symbol="RELIANCE", strategy="RADAR", state="BLOCKED", reason="cooldown")

        events = trade_journal.read_events(limit=10)

        self.assertEqual(len(events), 1)

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
