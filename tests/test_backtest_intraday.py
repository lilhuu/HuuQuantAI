from core.crypto_backtest_engine import CryptoBacktestEngine
from core.crypto_strategy_engine import CryptoStrategyEngine


def test_intrabar_sl_triggered_when_low_below_sl():
    result = CryptoBacktestEngine._detect_intrabar_stop(
        {"open": 100, "high": 105, "low": 94, "close": 101},
        entry_price=100,
        sl_price=95,
        tp_price=110,
    )

    assert result["trigger"] == "sl"
    assert result["fill_price"] == 95


def test_intrabar_tp_triggered_when_high_above_tp():
    result = CryptoBacktestEngine._detect_intrabar_stop(
        {"open": 100, "high": 112, "low": 98, "close": 101},
        entry_price=100,
        sl_price=95,
        tp_price=110,
    )

    assert result["trigger"] == "tp"


def test_intrabar_no_trigger_when_in_range():
    assert (
        CryptoBacktestEngine._detect_intrabar_stop(
            {"open": 100, "high": 108, "low": 96, "close": 101},
            entry_price=100,
            sl_price=95,
            tp_price=110,
        )
        is None
    )


def test_intrabar_both_hit_uses_open_distance():
    sl_first = CryptoBacktestEngine._detect_intrabar_stop(
        {"open": 96, "high": 112, "low": 94, "close": 100},
        entry_price=100,
        sl_price=95,
        tp_price=110,
    )
    tp_first = CryptoBacktestEngine._detect_intrabar_stop(
        {"open": 109, "high": 112, "low": 94, "close": 100},
        entry_price=100,
        sl_price=95,
        tp_price=110,
    )

    assert sl_first["trigger"] == "sl"
    assert tp_first["trigger"] == "tp"


def test_backtest_intrabar_trade_marked():
    engine = CryptoBacktestEngine(initial_cash=10000, fee_rate=0.001, slippage_rate=0, period="1h")
    strategy_engine = CryptoStrategyEngine()
    config = strategy_engine.normalize_configs(
        [
            {
                "strategy_id": "fast_momentum",
                "type": "momentum",
                "symbols": ["BTC/USDT"],
                "parameters": {
                    "lookback_period": 1,
                    "buy_threshold": 0.001,
                    "sell_threshold": -0.5,
                    "risk_per_trade_pct": 0.02,
                    "stop_loss_atr_multiplier": 1,
                    "take_profit_atr_multiplier": 3,
                    "min_position_value": 1,
                },
            }
        ],
        ["BTC/USDT"],
    )[0]
    candles = [
        {"symbol": "BTC/USDT", "period": "1h", "start_time": str(i), "open": 100, "high": 101 + i, "low": 99, "close": 100 + i, "volume": 1}
        for i in range(5)
    ]
    candles.append({"symbol": "BTC/USDT", "period": "1h", "start_time": "5", "open": 104, "high": 105, "low": 90, "close": 104, "volume": 1})

    result = engine.run({"BTC/USDT": candles}, config)

    assert any(trade.get("intrabar") for trade in result["trades"])
