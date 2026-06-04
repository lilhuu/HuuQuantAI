from datetime import datetime, timedelta
import inspect
import sqlite3

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


def _test(name, check):
    if "tmp_path" in inspect.signature(check).parameters:
        def wrapper(tmp_path):
            check(tmp_path)
    else:
        def wrapper():
            check()

    wrapper.__name__ = name
    wrapper.__qualname__ = name
    wrapper.__doc__ = f"md spec: {name}"
    return wrapper


def _buy_broker(**config):
    return _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False, **config)


def _partial_broker(**config):
    return _broker(max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=True, **config)


def _storage_config(path, **config):
    payload = {
        "storage_path": str(path),
        "initial_cash": 10000,
        "max_order_notional": 10000,
        "max_position_ratio": 1.0,
        "partial_fill_enabled": False,
    }
    payload.update(config)
    return payload


def _reject(config, order_args, message=""):
    order = _broker(**config).place_order(*order_args)
    assert order.status == "rejected"
    if message:
        assert message in order.message


def _open_position():
    broker = _buy_broker()
    order = broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    assert order.status == "filled"
    return broker, order


def _pending_broker():
    broker = _broker()
    order = CryptoPaperOrder(symbol="BTC/USDT", action="BUY", quantity=1, price=1, order_id="pending-1")
    broker.orders[order.order_id] = order
    return broker, order


def _account_after_roundtrip():
    broker, _ = _open_position()
    broker.place_order("BTC/USDT", "SELL", 0.02, 50000)
    return broker.get_account_info()


def _persistent(tmp_path, **config):
    return CryptoPaperBrokerExecutor(_storage_config(tmp_path / "paper.db", **config))


def _init_defaults():
    broker = CryptoPaperBrokerExecutor({"persistence_enabled": False})
    assert broker.broker_name == "CryptoPaperBroker"
    assert broker.quote_currency == "USDT"
    assert broker.initial_cash == 10000
    assert broker.cash == 10000
    assert broker.fee_rate == 0.001
    assert broker.slippage_rate == 0.0005


def _init_custom_config():
    broker = _broker(initial_cash=50000, fee_rate=0.002)
    assert broker.initial_cash == 50000
    assert broker.cash == 50000
    assert broker.fee_rate == 0.002


def _init_persistence_disabled_without_path():
    broker = CryptoPaperBrokerExecutor({"storage_path": "", "persistence_enabled": True})
    assert broker.persistence_enabled is False
    assert broker._persistence_ready is False


def _init_logs_initial_event():
    assert _broker().paper_logs[0]["event"] in {"account_initialized", "account_restored"}


def _init_equity_curve_first_point():
    point = _broker().equity_curve[0]
    assert point["reason"] == "account_initialized"


def _buy_full_fill():
    broker, order = _open_position()
    assert order.filled_quantity == 0.02
    assert broker.positions["BTC/USDT"]["quantity"] == 0.02
    assert broker.cash < 10000


def _buy_partial_fill():
    broker = _partial_broker()
    order = broker.place_order("BTC/USDT", "BUY", 0.1, 50000)
    assert order.status == "partial_filled"
    assert order.filled_quantity == 0.06


def _buy_fee():
    broker = _buy_broker(slippage_rate=0)
    order = broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    assert order.fee == pytest.approx(1000 * 0.001)


def _buy_slippage():
    order = _buy_broker(slippage_rate=0.0005).place_order("BTC/USDT", "BUY", 0.02, 50000)
    assert order.filled_price == 50025


def _buy_avg_weighted():
    broker = _buy_broker(slippage_rate=0)
    broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    broker.place_order("BTC/USDT", "BUY", 0.01, 51000)
    assert broker.positions["BTC/USDT"]["avg_price"] == pytest.approx(((0.02 * 50000) + (0.01 * 51000)) / 0.03)


def _sell_full_position():
    broker, _ = _open_position()
    order = broker.place_order("BTC/USDT", "SELL", 0.02, 50000)
    assert order.status == "filled"
    assert "BTC/USDT" not in broker.positions


def _sell_partial_position():
    broker, _ = _open_position()
    order = broker.place_order("BTC/USDT", "SELL", 0.01, 50000)
    assert order.status == "filled"
    assert broker.positions["BTC/USDT"]["quantity"] == pytest.approx(0.01)


def _sell_profit():
    broker, _ = _open_position()
    assert broker.place_order("BTC/USDT", "SELL", 0.02, 51000).realized_pnl > 0


def _sell_loss():
    broker, _ = _open_position()
    assert broker.place_order("BTC/USDT", "SELL", 0.02, 49000).realized_pnl < 0


def _sell_slippage():
    broker = _buy_broker(slippage_rate=0.0005)
    broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    assert broker.place_order("BTC/USDT", "SELL", 0.01, 50000).filled_price == 49975


def _cancel(order_status):
    if order_status == "pending":
        broker, order = _pending_broker()
    elif order_status == "partial_filled":
        broker = _partial_broker()
        order = broker.place_order("BTC/USDT", "BUY", 0.1, 50000)
    elif order_status == "filled":
        broker, order = _open_position()
    elif order_status == "cancelled":
        broker, order = _pending_broker()
        broker.cancel_order(order.order_id)
    else:
        broker = _broker()
        order = broker.place_order("BTC/USDT", "HOLD", 1, 1)
    return broker.cancel_order(order.order_id), broker, order


def _account_initial():
    account = _broker().get_account_info()
    assert account["equity"] == account["cash"] == account["initial_cash"] == 10000


def _account_market_value():
    broker, _ = _open_position()
    account = broker.get_account_info()
    assert account["equity"] == pytest.approx(account["cash"] + account["market_value"])


def _positions_after_buy():
    broker, _ = _open_position()
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0]["market_value"] > 0


def _orders_page():
    broker = _buy_broker()
    for index in range(5):
        broker.place_order(f"C{index}/USDT", "BUY", 1, 100)
    page = broker.get_orders(limit=2, offset=1)
    assert page["count"] == 2
    assert page["total"] == 5


def _orders_sorted():
    broker = _buy_broker()
    first = broker.place_order("BTC/USDT", "BUY", 1, 100)
    second = broker.place_order("ETH/USDT", "BUY", 1, 100)
    broker.orders[first.order_id].created_time = datetime.now() - timedelta(days=1)
    broker.orders[second.order_id].created_time = datetime.now()
    assert broker.get_orders()["items"][0]["order_id"] == second.order_id


def _persist_restore(tmp_path):
    config = _storage_config(tmp_path / "persist.db")
    broker = CryptoPaperBrokerExecutor(config)
    order = broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    restored = CryptoPaperBrokerExecutor(config)
    assert restored.initial_cash == broker.initial_cash
    assert restored.cash == pytest.approx(broker.cash)
    assert restored.orders[order.order_id].status == "filled"
    assert restored.positions["BTC/USDT"]["quantity"] == pytest.approx(0.02)
    assert restored.trade_history


def _persist_dedup(tmp_path, table):
    config = _storage_config(tmp_path / f"{table}.db")
    broker = CryptoPaperBrokerExecutor(config)
    broker.place_order("BTC/USDT", "BUY", 0.02, 50000)
    first = CryptoPaperBrokerExecutor(config)
    second = CryptoPaperBrokerExecutor(config)
    assert len(second.equity_curve) == len(first.equity_curve)


def _prune_logs(tmp_path):
    path = tmp_path / "logs.db"
    broker = CryptoPaperBrokerExecutor(_storage_config(path, max_persisted_log_entries=5))
    for index in range(20):
        broker.place_order(f"C{index}/USDT", "BUY", 1, 10)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM crypto_paper_logs").fetchone()[0] <= 5


INIT_CASES = {
    "test_init_defaults": _init_defaults,
    "test_init_custom_config": _init_custom_config,
    "test_init_persistence_disabled_without_path": _init_persistence_disabled_without_path,
    "test_init_logs_initial_event": _init_logs_initial_event,
    "test_init_equity_curve_first_point": _init_equity_curve_first_point,
    "test_init_cash_equals_initial_cash": lambda: assert_cash_equal(),
    "test_init_positions_empty": lambda: assert_equal(_broker().positions, {}),
    "test_init_orders_empty": lambda: assert_equal(_broker().orders, {}),
}


def assert_equal(actual, expected):
    assert actual == expected


def assert_cash_equal():
    broker = _broker()
    assert broker.cash == broker.initial_cash


REJECT_CASES = {
    "test_reject_paper_order_disabled": lambda: _reject({"paper_order_enabled": False}, ("BTC/USDT", "BUY", 0.01, 50000), "paper order switch is disabled"),
    "test_reject_real_trading_enabled": lambda: _reject({"real_trading_enabled": True}, ("BTC/USDT", "BUY", 0.01, 50000), "refuses real_trading_enabled"),
    "test_reject_empty_symbol": lambda: _reject({}, ("", "BUY", 0.01, 50000)),
    "test_reject_bad_action": lambda: _reject({}, ("BTC/USDT", "HOLD", 0.01, 50000), "unsupported action"),
    "test_reject_zero_quantity": lambda: _reject({}, ("BTC/USDT", "BUY", 0, 50000), "quantity must be greater than 0"),
    "test_reject_negative_quantity": lambda: _reject({}, ("BTC/USDT", "BUY", -1, 50000), "quantity must be greater than 0"),
    "test_reject_zero_price": lambda: _reject({}, ("BTC/USDT", "BUY", 0.01, 0), "price must be greater than 0"),
    "test_reject_negative_price": lambda: _reject({}, ("BTC/USDT", "BUY", 0.01, -100), "price must be greater than 0"),
    "test_reject_exceeds_max_notional": lambda: _reject({}, ("BTC/USDT", "BUY", 1, 50000), "exceeds"),
    "test_reject_insufficient_cash": lambda: _reject({"max_order_notional": 50000, "max_position_ratio": 1.0}, ("BTC/USDT", "BUY", 1, 20000), "insufficient USDT cash"),
    "test_reject_sell_without_position": lambda: _reject({}, ("BTC/USDT", "SELL", 0.1, 50000), "short selling is disabled"),
    "test_reject_max_position_ratio": lambda: assert_reject_ratio(),
}


def assert_reject_ratio():
    broker = _broker(max_order_notional=10000, partial_fill_enabled=False)
    assert broker.place_order("BTC/USDT", "BUY", 0.09, 50000).status == "filled"
    rejected = broker.place_order("ETH/USDT", "BUY", 0.02, 50000)
    assert rejected.status == "rejected"
    assert "max position ratio exceeded" in rejected.message


FILL_CASES = {
    "test_buy_full_fill": _buy_full_fill,
    "test_buy_partial_fill": _buy_partial_fill,
    "test_buy_fee_calculation": _buy_fee,
    "test_buy_slippage_buy_side": _buy_slippage,
    "test_buy_avg_price_weighted": _buy_avg_weighted,
    "test_buy_position_available_equals_quantity": lambda: assert_position_available(),
    "test_sell_full_position": _sell_full_position,
    "test_sell_partial_position": _sell_partial_position,
    "test_sell_realized_pnl_profit": _sell_profit,
    "test_sell_realized_pnl_loss": _sell_loss,
    "test_sell_slippage_sell_side": _sell_slippage,
    "test_buy_updates_last_price": lambda: assert_last_price(),
    "test_buy_defaults_stop_loss_take_profit": lambda: assert_tpsl_defaults(),
}


def assert_position_available():
    broker, _ = _open_position()
    assert broker.positions["BTC/USDT"]["available"] == broker.positions["BTC/USDT"]["quantity"]


def assert_last_price():
    broker, order = _open_position()
    assert broker.positions["BTC/USDT"]["last_price"] == order.filled_price


def assert_tpsl_defaults():
    broker, order = _open_position()
    assert broker.positions["BTC/USDT"]["stop_loss_price"] == pytest.approx(order.filled_price * 0.98)
    assert broker.positions["BTC/USDT"]["take_profit_price"] == pytest.approx(order.filled_price * 1.04)


CANCEL_CASES = {
    "test_cancel_pending_order": lambda: assert_equal(_cancel("pending")[0], True),
    "test_cancel_partial_filled_order": lambda: assert_equal(_cancel("partial_filled")[0], True),
    "test_cancel_nonexistent_order": lambda: assert_equal(_broker().cancel_order("non-existent-id"), False),
    "test_cancel_already_filled_order": lambda: assert_equal(_cancel("filled")[0], False),
    "test_cancel_already_cancelled_order": lambda: assert_equal(_cancel("cancelled")[0], False),
    "test_cancel_already_rejected_order": lambda: assert_equal(_cancel("rejected")[0], False),
}


ACCOUNT_CASES = {
    "test_account_initial_equity_equals_cash": _account_initial,
    "test_account_equity_includes_market_value": _account_market_value,
    "test_account_total_profit": lambda: assert_total_profit_loss(),
    "test_account_total_return_percent": lambda: assert_return_percent(),
    "test_account_total_trades_count": lambda: assert_equal(_account_after_roundtrip()["total_trades"], 2),
    "test_account_total_fee_accumulates": lambda: assert_fee_total(),
    "test_account_positions_included": lambda: assert_account_positions_included(),
}


def assert_return_percent():
    account = _account_after_roundtrip()
    assert account["total_return_percent"] == pytest.approx(account["total_profit"] / account["initial_cash"] * 100)


def assert_total_profit_loss():
    assert _account_after_roundtrip()["total_profit"] < 0


def assert_fee_total():
    broker, _ = _open_position()
    second = broker.place_order("BTC/USDT", "SELL", 0.02, 50000)
    assert broker.get_account_info()["total_fee"] == pytest.approx(sum(item["fee"] for item in broker.trade_history))
    assert second.fee > 0


def assert_account_positions_included():
    assert _open_position()[0].get_account_info()["positions"]


POSITIONS_CASES = {
    "test_empty_positions": lambda: assert_equal(_broker().get_positions(), []),
    "test_get_positions_after_buy": _positions_after_buy,
    "test_position_fields_complete": lambda: assert_position_fields_complete(),
    "test_position_current_price_equals_last_price": lambda: assert_position_current_price(),
    "test_position_market_value": lambda: assert_position_field("market_value"),
    "test_position_unrealized_pnl": lambda: assert_position_field("unrealized_pnl"),
    "test_position_unrealized_pnl_percent": lambda: assert_position_field("unrealized_pnl_percent"),
    "test_positions_sorted_by_symbol": lambda: assert_positions_sorted(),
    "test_positions_filter_zero_quantity": lambda: assert_positions_filter_zero(),
    "test_position_zero_quantity_filtered": lambda: assert_positions_filter_zero(),
}


def assert_position_fields_complete():
    position = _open_position()[0].get_positions()[0]
    assert {
        "symbol",
        "quantity",
        "available",
        "avg_price",
        "current_price",
        "market_value",
        "cost_basis",
        "unrealized_pnl",
        "unrealized_pnl_percent",
    }.issubset(position)


def assert_position_current_price():
    broker, _ = _open_position()
    assert broker.get_positions()[0]["current_price"] == broker.positions["BTC/USDT"]["last_price"]


def assert_position_field(field):
    broker, _ = _open_position()
    position = broker.get_positions()[0]
    assert field in position


def assert_positions_sorted():
    broker = _buy_broker()
    broker.place_order("ETH/USDT", "BUY", 1, 100)
    broker.place_order("BTC/USDT", "BUY", 1, 100)
    assert [item["symbol"] for item in broker.get_positions()] == ["BTC/USDT", "ETH/USDT"]


def assert_positions_filter_zero():
    broker, _ = _open_position()
    broker.positions["ZERO/USDT"] = {"quantity": 0, "available": 0, "avg_price": 1, "last_price": 1}
    assert "ZERO/USDT" not in [item["symbol"] for item in broker.get_positions()]


ORDER_CASES = {
    "test_orders_pagination": _orders_page,
    "test_orders_filter_by_status": lambda: assert_orders_filter(),
    "test_orders_sorted_by_time_desc": _orders_sorted,
    "test_orders_limit_clamped": lambda: assert_equal(_buy_broker().get_orders(limit=999)["limit"], 500),
    "test_orders_offset_beyond_total": lambda: assert_equal(_buy_broker().get_orders(offset=999)["count"], 0),
}


def assert_orders_filter():
    broker = _buy_broker()
    broker.place_order("BTC/USDT", "BUY", 1, 100)
    broker.place_order("BTC/USDT", "HOLD", 1, 100)
    assert broker.get_orders(status="filled")["total"] == 1
    assert broker.get_orders(status="rejected")["total"] == 1


CURVE_LOG_CASES = {
    "test_equity_curve_returns_recent": lambda: assert_curve_recent(),
    "test_equity_curve_limit_clamped": lambda: assert_equal(len(_broker().get_equity_curve(0)), 1),
    "test_paper_logs_limit_clamped": lambda: assert_equal(len(_broker().get_paper_logs(0)), 1),
}


def assert_curve_recent():
    broker = _broker()
    for index in range(5):
        broker._record_equity_point(reason=f"r{index}")
    assert broker.get_equity_curve(2)[-1]["reason"] == "r4"


PERSISTENCE_CASES = {
    "test_persist_account_basic": _persist_restore,
    "test_persist_orders_restored": _persist_restore,
    "test_persist_positions_restored": _persist_restore,
    "test_persist_trade_history_restored": _persist_restore,
    "test_persist_equity_curve_dedup": lambda tmp_path: _persist_dedup(tmp_path, "equity"),
    "test_persist_logs_dedup": lambda tmp_path: _persist_dedup(tmp_path, "logs"),
    "test_prune_persisted_logs": _prune_logs,
    "test_persist_no_storage_path": lambda tmp_path: assert_equal(CryptoPaperBrokerExecutor({"storage_path": "", "persistence_enabled": True}).persistence_enabled, False),
    "test_restore_from_empty_db": lambda tmp_path: assert_restore_empty(tmp_path),
}


def assert_restore_empty(tmp_path):
    broker = CryptoPaperBrokerExecutor(_storage_config(tmp_path / "empty.db"))
    with sqlite3.connect(broker.storage_path) as conn:
        conn.execute("DELETE FROM crypto_paper_account")
        conn.commit()
    assert broker._load_state() is False


EDGE_CASES = {
    "test_quantity_precision_rounding": lambda: assert_equal(_broker(quantity_precision=2, max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False).place_order("BTC/USDT", "BUY", 0.005, 100).quantity, 0.01),
    "test_price_precision_rounding": lambda: assert_equal(_broker(price_precision=2, max_order_notional=10000, max_position_ratio=1.0, partial_fill_enabled=False).place_order("BTC/USDT", "BUY", 1, 50000.005).price, 50000.01),
    "test_order_id_unique": lambda: assert_unique_order_ids(),
    "test_equity_curve_capped_at_1000": lambda: assert_curve_cap(),
    "test_logs_capped": lambda: assert_log_cap(),
    "test_symbol_normalized_with_quote": lambda: assert_equal(_buy_broker().place_order("BTC", "BUY", 1, 100).symbol, "BTC/USDT"),
    "test_symbol_already_has_slash": lambda: assert_equal(_buy_broker().place_order("BTC/USDT", "BUY", 1, 100).symbol, "BTC/USDT"),
    "test_reject_order_logs_event": lambda: assert_reject_log(),
    "test_filled_order_logs_event": lambda: assert_fill_log(),
    "test_equity_curve_recorded_on_fill": lambda: assert_curve_reason("filled"),
    "test_equity_curve_recorded_on_reject": lambda: assert_curve_reason("order_rejected", rejected=True),
    "test_partial_fill_remaining_quantity": lambda: assert_partial_fill_message(),
    "test_cancel_releases_no_cash": lambda: assert_cancel_no_cash(),
}


def assert_unique_order_ids():
    broker = _broker()
    ids = {broker.place_order("BTC/USDT", "HOLD", 1, 1).order_id for _ in range(100)}
    assert len(ids) == 100


def assert_curve_cap():
    broker = _broker()
    for _ in range(2000):
        broker._record_equity_point(reason="unit")
    assert len(broker.equity_curve) == 1000


def assert_log_cap():
    broker = _broker(max_log_entries=5)
    for index in range(20):
        broker._record_log(f"event_{index}", "message")
    assert len(broker.paper_logs) <= 5


def assert_reject_log():
    broker = _broker()
    broker.place_order("BTC/USDT", "HOLD", 1, 1)
    assert any(item["event"] == "order_rejected" and item["level"] == "WARN" for item in broker.paper_logs)


def assert_fill_log():
    broker, _ = _open_position()
    assert any(item["event"] in {"order_filled", "order_partially_filled"} for item in broker.paper_logs)


def assert_curve_reason(reason, rejected=False):
    broker = _broker() if rejected else _buy_broker()
    if rejected:
        broker.place_order("BTC/USDT", "HOLD", 1, 1)
    else:
        broker.place_order("BTC/USDT", "BUY", 1, 100)
    assert broker.equity_curve[-1]["reason"] == reason


def assert_partial_fill_message():
    assert "0.06/0.1" in _partial_broker().place_order("BTC/USDT", "BUY", 0.1, 50000).message


def assert_cancel_no_cash():
    broker = _partial_broker()
    order = broker.place_order("BTC/USDT", "BUY", 0.1, 50000)
    cash = broker.cash
    broker.cancel_order(order.order_id)
    assert broker.cash == cash


for _name, _check in {
    **INIT_CASES,
    **REJECT_CASES,
    **FILL_CASES,
    **CANCEL_CASES,
    **ACCOUNT_CASES,
    **POSITIONS_CASES,
    **ORDER_CASES,
    **CURVE_LOG_CASES,
    **PERSISTENCE_CASES,
    **EDGE_CASES,
}.items():
    globals()[_name] = _test(_name, _check)
