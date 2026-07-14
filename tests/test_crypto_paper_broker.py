import sqlite3
from unittest.mock import MagicMock

import pytest

from core.crypto_paper_broker import CryptoPaperBrokerExecutor, CryptoPaperOrder


def _broker(**config):
    defaults = {
        "initial_cash": 10000,
        "max_order_notional": 2000,
        "max_position_ratio": 0.5,
        "partial_fill_enabled": True,
        "partial_fill_min_notional": 3000,
        "partial_fill_ratio": 0.6,
        "persistence_enabled": False,
    }
    defaults.update(config)
    return CryptoPaperBrokerExecutor(defaults)


def test_init_defaults_custom_and_initial_state():
    default = CryptoPaperBrokerExecutor({"persistence_enabled": False})
    assert default.broker_name == "CryptoPaperBroker"
    assert default.quote_currency == "USDT"
    assert default.initial_cash == 10000
    assert default.cash == 10000
    assert default.fee_rate == 0.001
    assert default.slippage_rate == 0.0005
    assert default.persistence_enabled is False
    assert default._persistence_ready is False
    assert default.positions == {}
    assert default.orders == {}
    assert default.paper_logs[0]["event"] == "account_initialized"
    assert default.equity_curve[0]["reason"] == "account_initialized"

    custom = _broker(initial_cash=50000, fee_rate=0.002)
    assert custom.initial_cash == 50000
    assert custom.cash == 50000
    assert custom.fee_rate == 0.002


@pytest.mark.parametrize(
    ("config", "order_args", "message"),
    [
        ({"paper_order_enabled": False}, ("BTC/USDT", "BUY", 0.01, 50000), "paper order switch is disabled"),
        ({"real_trading_enabled": True}, ("BTC/USDT", "BUY", 0.01, 50000), "refuses real_trading_enabled"),
        ({}, ("", "BUY", 0.01, 50000), "symbol is required"),
        ({}, ("BTC/USDT", "HOLD", 0.01, 50000), "unsupported action"),
        ({}, ("BTC/USDT", "BUY", 0, 50000), "quantity must be greater than 0"),
        ({}, ("BTC/USDT", "BUY", -1, 50000), "quantity must be greater than 0"),
        ({}, ("BTC/USDT", "BUY", 0.01, 0), "price must be greater than 0"),
        ({}, ("BTC/USDT", "BUY", 0.01, -100), "price must be greater than 0"),
        ({}, ("BTC/USDT", "BUY", 1, 50000), "exceeds"),
        ({"max_order_notional": 50000, "max_position_ratio": 1.0}, ("BTC/USDT", "BUY", 1, 20000), "insufficient USDT cash"),
        ({}, ("BTC/USDT", "SELL", 0.1, 50000), "short selling is disabled"),
    ],
)
def test_place_order_rejects_invalid_orders(config, order_args, message):
    broker = _broker(**config)
    order = broker.place_order(*order_args)

    assert order.status == "rejected"
    assert message in order.message
    assert any(item["event"] == "order_rejected" and item["level"] == "WARN" for item in broker.paper_logs)
    assert broker.equity_curve[-1]["reason"] == "order_rejected"


def test_reject_max_position_ratio():
    broker = _broker(max_order_notional=10000, partial_fill_enabled=False)
    assert broker.place_order("BTC/USDT", "BUY", 0.09, 50000).status == "filled"
    rejected = broker.place_order("ETH/USDT", "BUY", 0.02, 50000)
    assert rejected.status == "rejected"
    assert "max position ratio exceeded" in rejected.message


def test_buy_full_fill_fee_slippage_position_and_tpsl_defaults():
    broker = _broker(partial_fill_enabled=False)
    order = broker.place_order("BTC/USDT", "BUY", 0.02, 50000)

    assert order.status == "filled"
    assert order.filled_quantity == 0.02
    assert order.filled_price == 50025
    assert order.fee == pytest.approx(1000.5 * 0.001)
    assert broker.cash == pytest.approx(10000 - 1000.5 - order.fee)
    position = broker.positions["BTC/USDT"]
    assert position["quantity"] == 0.02
    assert position["available"] == position["quantity"]
    assert position["last_price"] == 50025
    assert position["stop_loss_price"] == pytest.approx(50025 * 0.98)
    assert position["take_profit_price"] == pytest.approx(50025 * 1.04)
    assert any(item["event"] == "order_filled" for item in broker.paper_logs)
    assert broker.equity_curve[-1]["reason"] == "filled"


def test_buy_partial_fill_and_cancel():
    broker = _broker(max_order_notional=10000)
    order = broker.place_order("BTC/USDT", "BUY", 0.1, 50000)

    assert order.status == "partial_filled"
    assert order.filled_quantity == 0.06
    assert "0.06/0.1" in order.message
    assert broker.cancel_order(order.order_id) is True
    assert broker.orders[order.order_id].status == "cancelled"
    assert broker.cancel_order(order.order_id) is False
    assert broker.cancel_order("bad-id") is False


def test_buy_weighted_average_and_sell_profit_loss_slippage():
    broker = _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False, slippage_rate=0)
    first = broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    second = broker.place_order("BTC/USDT", "BUY", 0.01, 51000)
    assert first.status == second.status == "filled"
    assert broker.positions["BTC/USDT"]["avg_price"] == pytest.approx(((0.02 * 50000) + (0.01 * 51000)) / 0.03)

    profit = broker.place_order("BTC/USDT", "SELL", 0.01, 52000)
    assert profit.status == "filled"
    assert profit.realized_pnl > 0
    assert broker.positions["BTC/USDT"]["quantity"] == 0.02

    loss = broker.place_order("BTC/USDT", "SELL", 0.02, 49000)
    assert loss.status == "filled"
    assert loss.realized_pnl < 0
    assert "BTC/USDT" not in broker.positions

    slipped = _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False, slippage_rate=0.0005)
    slipped.place_order("ETH/USDT", "BUY", 1, 1000)
    sell = slipped.place_order("ETH/USDT", "SELL", 1, 1000)
    assert sell.filled_price == 999.5


def test_cancel_filled_order_returns_false():
    broker = _broker(partial_fill_enabled=False)
    order = broker.place_order("BTC/USDT", "BUY", 0.01, 50000)
    assert order.status == "filled"
    assert broker.cancel_order(order.order_id) is False


def test_persistence_restore_and_wal(tmp_path):
    storage_path = tmp_path / "paper.db"
    config = {
        "storage_path": str(storage_path),
        "initial_cash": 10000,
        "max_order_notional": 5000,
        "max_position_ratio": 1.0,
        "partial_fill_enabled": False,
    }
    broker = CryptoPaperBrokerExecutor(config)
    order = broker.place_order("BTC/USDT", "BUY", 0.02, 1000)

    restored = CryptoPaperBrokerExecutor(config)
    assert restored.cash == broker.cash
    assert restored.orders[order.order_id].status == "filled"
    assert restored.positions["BTC/USDT"]["quantity"] == 0.02
    assert restored.trade_history
    assert restored.equity_curve
    assert any(item["event"] == "account_restored" for item in restored.paper_logs)

    with sqlite3.connect(storage_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_persistence_initialization_failure_blocks_trading(monkeypatch, tmp_path):
    def fail_connect(_self):
        raise OSError("disk unavailable")

    monkeypatch.setattr(CryptoPaperBrokerExecutor, "_connect", fail_connect)
    broker = CryptoPaperBrokerExecutor(
        {
            "storage_path": str(tmp_path / "unavailable.db"),
            "max_order_notional": 5000,
            "max_position_ratio": 1.0,
        }
    )

    order = broker.place_order("BTC/USDT", "BUY", 0.01, 1000)

    assert broker.is_connected is False
    assert order.status == "rejected"
    assert "persistence" in order.message.lower()
    assert broker.cash == 10_000
    assert broker.positions == {}
    assert broker.trade_history == []


def test_order_persistence_failure_rolls_back_memory_state(monkeypatch, tmp_path):
    broker = CryptoPaperBrokerExecutor(
        {
            "storage_path": str(tmp_path / "runtime_failure.db"),
            "max_order_notional": 5000,
            "max_position_ratio": 1.0,
            "partial_fill_enabled": False,
        }
    )
    before_cash = broker.cash
    before_order_ids = set(broker.orders)
    before_equity_count = len(broker.equity_curve)
    monkeypatch.setattr(
        broker,
        "_persist_state",
        MagicMock(side_effect=OSError("disk full")),
    )

    order = broker.place_order("BTC/USDT", "BUY", 0.01, 1000)

    assert order.status == "rejected"
    assert "persistence" in order.message.lower()
    assert broker.is_connected is False
    assert broker.cash == before_cash
    assert broker.positions == {}
    assert broker.trade_history == []
    assert set(broker.orders) == before_order_ids
    assert len(broker.equity_curve) == before_equity_count


def test_order_query_pagination_status_and_response_shape():
    broker = _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False)
    orders = [broker.place_order(f"COIN{index}/USDT", "BUY", 1, 10) for index in range(5)]

    page = broker.get_orders(limit=2, offset=1)
    assert page["count"] == 2
    assert page["total"] == 5
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert set(orders[0].to_response()) >= {"order_id", "status", "symbol", "action", "quantity", "price"}
    assert broker.get_orders(status="filled")["total"] == 5


def test_account_positions_equity_curve_and_logs_limits():
    broker = _broker(max_log_entries=5)
    for index in range(20):
        broker._record_log(f"event_{index}", "message")
    assert len(broker.paper_logs) == 5

    for _ in range(1100):
        broker._record_equity_point(reason="unit")
    assert len(broker.equity_curve) == 1000
    assert len(broker.get_equity_curve(2000)) == 1000
    assert len(broker.get_paper_logs(999)) == 5

    account = broker.get_account_info()
    assert account["equity"] == account["cash"] + account["market_value"]
    assert account["total_trades"] == len(broker.trade_history)


def test_precision_order_id_symbol_normalization_and_logs(tmp_path):
    broker = _broker(quantity_precision=2, price_precision=2, max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False)
    order = broker.place_order("BTC", "BUY", 0.005, 50000.005)
    assert order.symbol == "BTC/USDT"
    assert order.quantity == 0.01
    assert order.price == 50000.01

    ids = {broker.place_order("BTC/USDT", "HOLD", 1, 1).order_id for _ in range(100)}
    assert len(ids) == 100

    storage_path = tmp_path / "logs.db"
    persistent = CryptoPaperBrokerExecutor(
        {
            "storage_path": str(storage_path),
            "max_order_notional": 10000,
            "max_position_ratio": 1.0,
            "partial_fill_enabled": False,
            "max_persisted_log_entries": 3,
        }
    )
    for index in range(5):
        persistent.place_order(f"T{index}/USDT", "BUY", 1, 10)
    with sqlite3.connect(storage_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM crypto_paper_logs").fetchone()[0] <= 3


def test_cancel_pending_partial_nonexistent_filled_cancelled_and_rejected_orders():
    broker = _broker(max_order_notional=10000)
    pending = CryptoPaperOrder(symbol="BTC/USDT", action="BUY", quantity=1, price=1, order_id="pending-1")
    broker.orders[pending.order_id] = pending
    assert broker.cancel_order("pending-1") is True
    assert broker.orders["pending-1"].status == "cancelled"
    assert broker.cancel_order("pending-1") is False

    partial = broker.place_order("ETH/USDT", "BUY", 10, 500)
    assert partial.status == "partial_filled"
    assert broker.cancel_order(partial.order_id) is True

    filled = _broker(partial_fill_enabled=False).place_order("BTC/USDT", "BUY", 0.01, 50000)
    filled_broker = _broker(partial_fill_enabled=False)
    filled_broker.orders[filled.order_id] = filled
    assert filled_broker.cancel_order(filled.order_id) is False

    rejected = broker.place_order("BTC/USDT", "HOLD", 1, 1)
    assert broker.cancel_order(rejected.order_id) is False
    assert broker.cancel_order("non-existent-id") is False


def test_account_initial_equity_market_value_profit_return_trades_fee_and_positions():
    broker = _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False)
    initial = broker.get_account_info()
    assert initial["equity"] == initial["cash"] == initial["initial_cash"] == 10000

    buy = broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    account = broker.get_account_info()
    assert account["equity"] == pytest.approx(account["cash"] + account["market_value"])
    assert account["positions"][0]["symbol"] == "BTC/USDT"
    assert account["total_trades"] == 1
    assert account["total_fee"] == pytest.approx(buy.fee)

    sell = broker.place_order("BTC/USDT", "SELL", 0.02, 50000)
    closed = broker.get_account_info()
    assert sell.status == "filled"
    assert closed["total_profit"] < 0
    assert closed["total_return_percent"] == pytest.approx(closed["total_profit"] / 10000 * 100)
    assert closed["total_trades"] == 2


def test_positions_empty_after_init_sorted_market_value_and_unrealized_fields():
    broker = _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False)
    assert broker.get_positions() == []

    broker.place_order("ETH/USDT", "BUY", 1, 1000)
    broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    broker.positions["BTC/USDT"]["last_price"] = 51000
    positions = broker.get_positions()

    assert [item["symbol"] for item in positions] == ["BTC/USDT", "ETH/USDT"]
    btc = positions[0]
    assert btc["available"] == btc["quantity"]
    assert btc["market_value"] == pytest.approx(btc["quantity"] * btc["current_price"])
    assert btc["cost_basis"] == pytest.approx(btc["quantity"] * btc["avg_price"])
    assert btc["unrealized_pnl"] == pytest.approx(btc["market_value"] - btc["cost_basis"])
    assert btc["unrealized_pnl_percent"] == pytest.approx(btc["unrealized_pnl"] / btc["cost_basis"] * 100)


def test_orders_filters_limits_offsets_and_sorting():
    broker = _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False)
    first = broker.place_order("BTC/USDT", "BUY", 0.01, 50000)
    second = broker.place_order("ETH/USDT", "BUY", 1, 1000)
    rejected = broker.place_order("SOL/USDT", "HOLD", 1, 100)

    all_orders = broker.get_orders(limit=500, offset=-1)
    assert all_orders["count"] == 3
    assert all_orders["offset"] == 0
    assert {item["order_id"] for item in all_orders["items"]} == {first.order_id, second.order_id, rejected.order_id}
    assert broker.get_orders(status="filled")["total"] == 2
    assert broker.get_orders(status="rejected")["items"][0]["order_id"] == rejected.order_id
    assert broker.get_orders(limit=0)["limit"] == 100
    assert broker.get_orders(limit=999)["limit"] == 500
    assert {first.order_id, second.order_id}.issubset(set(broker.orders))


def test_equity_curve_and_logs_limit_bounds_and_latest_items():
    broker = _broker(max_log_entries=600)
    for index in range(20):
        broker._record_equity_point(reason=f"point_{index}")
        broker._record_log(f"log_{index}", "message")

    assert len(broker.get_equity_curve(5)) == 5
    assert broker.get_equity_curve(5)[-1]["reason"] == "point_19"
    assert len(broker.get_paper_logs(5)) == 5
    assert broker.get_paper_logs(5)[-1]["event"] == "log_19"


def test_persist_orders_positions_trades_account_and_deduplicated_curves_logs(tmp_path):
    storage_path = tmp_path / "persist_all.db"
    config = {
        "storage_path": str(storage_path),
        "initial_cash": 12345,
        "max_order_notional": 10000,
        "max_position_ratio": 1.0,
        "partial_fill_enabled": False,
    }
    broker = CryptoPaperBrokerExecutor(config)
    filled = broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    rejected = broker.place_order("BTC/USDT", "HOLD", 1, 1)
    before_equity_count = len(broker.equity_curve)
    before_log_keys = {
        (item["event"], item["order_id"], item["symbol"], item["message"])
        for item in broker.paper_logs
    }

    restored = CryptoPaperBrokerExecutor(config)
    restored_again = CryptoPaperBrokerExecutor(config)

    assert restored.initial_cash == broker.initial_cash == 12345
    assert restored.cash == pytest.approx(broker.cash)
    assert restored.broker_name == broker.broker_name
    assert restored.quote_currency == broker.quote_currency
    assert restored.orders[filled.order_id].status == "filled"
    assert restored.orders[rejected.order_id].status == "rejected"
    assert restored.positions["BTC/USDT"]["quantity"] == pytest.approx(0.02)
    assert restored.trade_history[0]["order_id"] == filled.order_id
    assert len(restored_again.equity_curve) == before_equity_count
    assert before_log_keys.issubset(
        {
            (item["event"], item["order_id"], item["symbol"], item["message"])
            for item in restored_again.paper_logs
        }
    )


def test_persist_no_storage_path_and_restore_from_empty_db(tmp_path):
    no_path = CryptoPaperBrokerExecutor({"storage_path": "", "persistence_enabled": True})
    assert no_path.persistence_enabled is False
    no_path._persist_state()

    empty_path = tmp_path / "empty.db"
    empty = CryptoPaperBrokerExecutor({"storage_path": str(empty_path), "persistence_enabled": True})
    assert empty._load_state() is True
    with sqlite3.connect(empty_path) as conn:
        conn.execute("DELETE FROM crypto_paper_account")
        conn.commit()
    fresh = CryptoPaperBrokerExecutor({"storage_path": str(empty_path), "persistence_enabled": True})
    assert fresh.paper_logs[0]["event"] == "account_initialized"


def test_sell_partial_position_and_cancel_releases_no_cash():
    broker = _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False)
    broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    sell = broker.place_order("BTC/USDT", "SELL", 0.01, 51000)
    assert sell.status == "filled"
    assert broker.positions["BTC/USDT"]["quantity"] == pytest.approx(0.01)
    assert broker.positions["BTC/USDT"]["available"] == pytest.approx(0.01)

    partial_broker = _broker(max_order_notional=10000)
    partial = partial_broker.place_order("ETH/USDT", "BUY", 10, 500)
    cash_after_partial = partial_broker.cash
    assert partial_broker.cancel_order(partial.order_id) is True
    assert partial_broker.cash == cash_after_partial


def test_custom_stop_loss_take_profit_override_defaults():
    broker = _broker(partial_fill_enabled=False)
    order = broker.place_order(
        "BTC/USDT",
        "BUY",
        0.01,
        50000,
        stop_loss_price=45000,
        take_profit_price=55000,
    )
    assert order.status == "filled"
    assert broker.positions["BTC/USDT"]["stop_loss_price"] == 45000
    assert broker.positions["BTC/USDT"]["take_profit_price"] == 55000


def test_ai_protective_exit_persists_and_closes_position(tmp_path):
    storage_path = tmp_path / "protected-position.db"
    broker = _broker(
        storage_path=str(storage_path),
        persistence_enabled=True,
        partial_fill_enabled=False,
        slippage_rate=0,
    )
    order = broker.place_order(
        "BTC/USDT",
        "BUY",
        0.01,
        50000,
        strategy="ai-supervised:SIG_1",
        stop_loss_price=49000,
        take_profit_price=52000,
    )

    assert order.status == "filled"
    assert broker.positions["BTC/USDT"]["protection_enabled"] is True
    assert broker.positions["BTC/USDT"]["source_strategy"] == "ai-supervised:SIG_1"

    restored = _broker(
        storage_path=str(storage_path),
        persistence_enabled=True,
        partial_fill_enabled=False,
        slippage_rate=0,
    )
    exits = restored.process_protective_exits({"BTC/USDT": 48900})

    assert len(exits) == 1
    assert exits[0]["action"] == "SELL"
    assert exits[0]["strategy"] == "protective_stop_loss"
    assert "BTC/USDT" not in restored.positions
