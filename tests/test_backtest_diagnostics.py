from core.backtest_validation import categorize_no_entry_reason, create_backtest_diagnostics
from core.crypto_backtest_engine import CryptoBacktestEngine
from core.crypto_strategy_engine import StrategyConfig


def test_categorize_no_entry_reason():
    assert categorize_no_entry_reason("momentum", "regime range blocked") == "trend_regime_not_ready"
    assert categorize_no_entry_reason("rsi", "RSI not extreme") == "mean_reversion_not_extreme"
    assert categorize_no_entry_reason("dual_ma", "plain hold") == "other_hold"


def test_create_backtest_diagnostics_cost_ratio():
    diagnostics = create_backtest_diagnostics(
        no_entry_counts={"other_hold": 3},
        exit_counts={"sl": 1, "tp": 2},
        win_pnls=[10, 20],
        loss_pnls=[-5],
        total_fees=2,
        total_execution_cost=1,
    )

    payload = diagnostics.to_dict()
    assert payload["no_entry_reasons"][0] == {"reason": "other_hold", "count": 3}
    assert payload["stop_loss_count"] == 1
    assert payload["take_profit_count"] == 2
    assert payload["gross_profit"] == 30
    assert payload["fee_slippage_to_gross_profit_pct"] == 10


def test_crypto_backtest_returns_diagnostics_for_hold_bars():
    market_data = {
        "BTC/USDT": [
            {"start_time": f"2026-05-01T0{i}:00:00+00:00", "close": 100.0, "high": 101.0, "low": 99.0}
            for i in range(8)
        ]
    }
    config = StrategyConfig(
        strategy_id="unit_rsi",
        type="rsi",
        symbols=["BTC/USDT"],
        parameters={"period": 14},
    )

    result = CryptoBacktestEngine().run(market_data, config)

    assert "diagnostics" in result
    assert result["diagnostics"]["no_entry_reasons"]
    assert result["diagnostics"]["no_entry_reasons"][0]["reason"] in {"mean_reversion_not_extreme", "other_hold"}
