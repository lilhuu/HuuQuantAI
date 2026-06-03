import sqlite3

import pytest

from core.crypto_paper_broker import CryptoPaperBrokerExecutor


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
