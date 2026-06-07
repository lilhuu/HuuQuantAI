# HuuQuantAI 核心模块测试规格

> 为 `auto_trading_engine`、`crypto_paper_broker`、`crypto_service` 三个核心模块的单元测试规格文档。
> 可直接交给 Codex 或其它 AI 编程助手按此规格实现。

---

## 一、`core/auto_trading_engine.py` — 自动交易引擎

**文件**: `tests/test_auto_trading.py`（已存在，需扩充）

**依赖**: 无外部 mock 需求，可直接实例化 `AutoTradingEngine` / `DecisionPipeline` / `AutoTradingConfig` / `RiskState`

---

### 1.1 `AutoTradingConfig.from_dict()` — 配置解析

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 1 | `test_config_defaults` | `{}` 或 `None` | 所有字段等于类默认值：`enabled=False`, `mode="paper"`, `symbols=["BTC/USDT","ETH/USDT","SOL/USDT"]`, `scan_interval_seconds=30`, `max_positions=3` 等 |
| 2 | `test_config_symbols_normalized` | `{"symbols": ["btc/usdt", "eth/usdt"]}` | symbols 转为大写：`["BTC/USDT", "ETH/USDT"]` |
| 3 | `test_config_symbols_empty_fallback` | `{"symbols": []}` | 回退到默认 `["BTC/USDT", "ETH/USDT", "SOL/USDT"]` |
| 4 | `test_config_scan_interval_clamped_min` | `{"scan_interval_seconds": 0}` | 钳制为 `5` |
| 5 | `test_config_scan_interval_clamped_max` | `{"scan_interval_seconds": 9999}` | 钳制为 `3600` |
| 6 | `test_config_max_positions_clamped_min` | `{"max_positions": 0}` | 钳制为 `1` |
| 7 | `test_config_max_positions_clamped_max` | `{"max_positions": 999}` | 钳制为 `20` |
| 8 | `test_config_confidence_clamped_min` | `{"confidence_threshold": -0.5}` | 钳制为 `0.0` |
| 9 | `test_config_confidence_clamped_max` | `{"confidence_threshold": 2.0}` | 钳制为 `1.0` |
| 10 | `test_config_cooldown_clamped_min` | `{"cooldown_minutes": 0}` | 钳制为 `1` |
| 11 | `test_config_cooldown_clamped_max` | `{"cooldown_minutes": 99999}` | 钳制为 `1440` |
| 12 | `test_config_strategies_default` | 不传 `strategies` | 返回 `_default_strategies(symbols)` 的 3 个策略（auto_rsi, auto_macd, auto_momentum） |
| 13 | `test_config_to_dict_roundtrip` | 创建 config → `to_dict()` → `from_dict()` | 往返后所有字段值一致 |
| 14 | `test_config_mode_always_paper` | `{"mode": "live"}` | `config.mode` 强制为 `"paper"` |
| 15 | `test_config_real_trading_always_false` | `{"real_trading_enabled": True}` | `config.real_trading_enabled` 强制为 `False`（无论是 `from_dict` 还是 `to_dict`） |
| 16 | `test_config_per_trade_ratio_clamped_min` | `{"per_trade_position_ratio": 0}` | 钳制为 `0.001` |
| 17 | `test_config_per_trade_ratio_clamped_max` | `{"per_trade_position_ratio": 2.0}` | 钳制为 `1.0` |

---

### 1.2 `AutoTradingEngine` 生命周期状态机

| # | 测试用例 | 操作序列 | 期望最终状态 |
|---|---------|----------|-------------|
| 18 | `test_initial_state_stopped` | 创建 engine | `state == "stopped"`, `enabled == False`, `cycle_count == 0`, `order_count == 0`, `signal_count == 0` |
| 19 | `test_start_transitions_to_running` | `start()` | `state == "running"`, `enabled == True` |
| 20 | `test_pause_from_running` | `start()` → `pause()` | `state == "paused"`, `enabled == False`, `loop_running == False` |
| 21 | `test_stop_from_running` | `start()` → `stop()` | `state == "stopped"`, `enabled == False` |
| 22 | `test_resume_from_paused` | `start()` → `pause()` → `start()` | `state == "running"` |
| 23 | `test_start_blocked_when_real_trading` | config 含 `real_trading_enabled=True` → `start()` | `state == "blocked"`, 日志含 "real trading is blocked" |
| 24 | `test_start_blocked_by_cooldown` | `risk_state.cooldown_until` 设为未来时间 → `start()` | `state == "paused"`, `last_message` 含 "cooling down" |
| 25 | `test_start_clears_kill_switch` | `risk_state.kill_switch_active=True` → `start()` | `kill_switch_active == False`, `reason == ""` |
| 26 | `test_status_returns_all_fields` | `status()` | dict 包含所有关键字段：state, enabled, mode, config, last_run_at, last_message, cycle_count, signal_count, order_count, last_decisions, logs, risk_state, real_trading_enabled, loop_running, next_run_at, last_error_type |

---

### 1.3 `DecisionPipeline.build_one()` — 决策管线

> 辅助函数（写在测试文件中）：
> ```python
> def _make_pipeline(config=None, risk_state=None, cooldown=False):
>     config = config or AutoTradingConfig()
>     risk_state = risk_state or RiskState()
>     return DecisionPipeline(config, risk_state, cooldown)
>
> def _make_base_args(**overrides):
>     """返回 build_one 所需的完整参数字典，overrides 可覆盖任意字段。"""
>     defaults = dict(
>         symbol="BTC/USDT", action="BUY", price=50000.0, confidence=0.5,
>         strategy_id="test_strategy", reason="test", candidate={},
>         equity=10000.0, cash=10000.0, positions={},
>         current_position_count=0, place_orders=True,
>     )
>     defaults.update(overrides)
>     return defaults
> ```

#### 通用门控（所有 action 共享）

| # | 测试用例 | 覆盖的条件 | 期望 |
|---|---------|-----------|------|
| 27 | `test_gate_real_trading_blocked` | `config.real_trading_enabled=True` | `status="skipped"`, `message="real trading is blocked"`, steps 包含 `real_trading_gate:fail` |
| 28 | `test_gate_real_trading_pass` | 正常 paper 模式 | steps 包含 `real_trading_gate:pass` |
| 29 | `test_gate_cooldown_active` | `cooldown_active=True`, `risk_state.cooldown_until="2099-01-01T00:00:00"` | `status="skipped"`, message 含 "risk cooldown active" |
| 30 | `test_gate_kill_switch_active` | `risk_state.kill_switch_active=True`, `risk_state.reason="manual stop"` | `status="skipped"`, `message="manual stop"` |
| 31 | `test_gate_price_zero` | `price=0` | `status="skipped"`, `message="missing executable price"` |
| 32 | `test_gate_price_negative` | `price=-100` | `status="skipped"`, `message="missing executable price"` |
| 33 | `test_gate_confidence_below_threshold` | `confidence=0.1`, `config.confidence_threshold=0.35` | `status="skipped"`, message 含 "confidence below threshold 0.35" |
| 34 | `test_gate_confidence_exactly_at_threshold` | `confidence=0.35`, `config.confidence_threshold=0.35` | 不应被 confidence 门控阻挡（`>=`） |
| 35 | `test_gate_preview_mode` | `place_orders=False` | `status="simulated"`, message 含 "decision preview only" |

#### BUY 专属门控

| # | 测试用例 | 条件 | 期望 |
|---|---------|------|------|
| 36 | `test_buy_duplicate_position_blocked` | `action="BUY"`, `quantity_held=1.0` | `status="skipped"`, message="position already exists", steps 含 `duplicate_position:fail` |
| 37 | `test_buy_duplicate_position_pass` | `action="BUY"`, `quantity_held=0` | steps 含 `duplicate_position:pass` |
| 38 | `test_buy_max_positions_reached` | `action="BUY"`, `current_position_count=3`, `config.max_positions=3` | `status="skipped"`, "max open positions reached" |
| 39 | `test_buy_max_positions_under_limit` | `action="BUY"`, `current_position_count=2`, `config.max_positions=3` | steps 含 `max_positions:pass` |
| 40 | `test_buy_notional_below_min` | `equity=100`, `cash=100`, `price=100`, `config.min_order_notional=999` | `status="skipped"`, steps 含 `notional:fail` |
| 41 | `test_buy_notional_exceeds_cash` | `equity=10000`, `cash=500`, `price=50000`, `config.per_trade_position_ratio=0.1` | notional 被 cash 限制，<= 500 |
| 42 | `test_buy_notional_capped_by_max_order` | `equity=100000`, `cash=100000`, `price=100`, `config.max_order_notional=1000`, `config.per_trade_position_ratio=1.0` | `notional=1000`（被 max_order_notional 限制） |
| 43 | `test_buy_quantity_rounded_to_zero` | `equity=1`, `cash=1`, `price=1000000` | `status="skipped"`, "quantity rounded to zero" |
| 44 | `test_buy_success_basic` | `action="BUY"`, `price=50000`, `equity=10000`, `cash=10000`, `confidence=0.5`, `config.per_trade_position_ratio=0.1`, `config.max_order_notional=2000` | `quantity=0.02` (1000/50000), `notional≈1000`, status 为 "ready"（place_orders=True）或 "simulated"（place_orders=False） |
| 45 | `test_buy_success_all_steps_present` | 成功的 BUY | steps 按顺序包含：real_trading_gate, risk_cooldown, kill_switch, market_data, confidence, submit_mode, duplicate_position, max_positions, notional, quantity 全部 pass |

#### SELL 专属门控

| # | 测试用例 | 条件 | 期望 |
|---|---------|------|------|
| 46 | `test_sell_no_position_blocked` | `action="SELL"`, `quantity_held=0` | `status="skipped"`, message="no position to sell; short selling disabled" |
| 47 | `test_sell_with_position_success` | `action="SELL"`, `quantity_held=1.5`, `price=50000` | `quantity=1.5`, `notional=75000.0` |
| 48 | `test_sell_quantity_matches_held` | `action="SELL"`, `quantity_held=0.12345678` | `quantity` 完全等于持有的 quantity（清仓） |

---

### 1.4 风险状态管理

| # | 测试用例 | 操作 | 期望 |
|---|---------|------|------|
| 49 | `test_risk_state_daily_reset` | 设 `risk_state.trading_day="2025-01-01"`, `day_start_equity=5000`; 调用 `_update_risk_state({"equity": 10000})` | `trading_day` 更新为今天, `day_start_equity=10000`, `daily_pnl=0` |
| 50 | `test_risk_state_daily_pnl_calculation` | `day_start_equity=10000`; `_update_risk_state({"equity": 9500})` | `daily_pnl=-500` |
| 51 | `test_kill_switch_on_daily_loss` | `config.max_daily_loss=200`, `day_start_equity=10000`; `_update_risk_state({"equity": 9700})` | `kill_switch_active=True`, `state="paused"` |
| 52 | `test_no_kill_switch_below_daily_loss_limit` | `config.max_daily_loss=500`, `day_start_equity=10000`; `_update_risk_state({"equity": 9600})` | `kill_switch_active=False`（loss=400 < 500） |
| 53 | `test_consecutive_losses_tracking` | `record_order_result(decision, {"status": "filled", "realized_pnl": -100})` × 3 | `consecutive_losses=3` |
| 54 | `test_consecutive_losses_reset_on_win` | 3 losses → 1 win (`realized_pnl=50`) | `consecutive_losses=0` |
| 55 | `test_consecutive_losses_not_counted_on_pending` | `record_order_result` with `status="pending"` | `order_count` 和 `consecutive_losses` 不变（只有 filled/partial_filled 计数） |
| 56 | `test_kill_switch_on_consecutive_losses` | `config.max_consecutive_losses=3`; 3 consecutive losses | `kill_switch_active=True`, reason 含 "consecutive losses" |
| 57 | `test_cooldown_expires` | `cooldown_until` 设为过去时间; 调用 `_cooldown_active()` | 返回 `False`, `kill_switch_active` 被自动清除 |
| 58 | `test_cooldown_still_active` | `cooldown_until` 设为未来时间 | `_cooldown_active()` 返回 `True` |
| 59 | `test_cooldown_invalid_iso_format` | `cooldown_until="not-a-date"` | `_cooldown_active()` 返回 `False`（不崩溃） |

---

### 1.5 `build_order_decisions()` 集成

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 60 | `test_empty_signals` | `strategy_result={"signals": [], "summary": [], "winners": []}` | decisions 列表为空 |
| 61 | `test_no_candidates` | `strategy_result` 不含 BUY/SELL action | decisions 列表为空 |
| 62 | `test_single_buy_signal` | 1 个 BUY signal in summary | 1 个 decision，symbol/action/quantity 对应 |
| 63 | `test_duplicate_symbol_action_deduped` | 2 个相同 symbol+action 的 candidate | 只产出一个 decision（`seen` set 去重） |
| 64 | `test_winners_priority_over_summary` | winners 和 summary 都有信号 | 使用 winners（优先） |
| 65 | `test_cash_deducted_after_buy_ready` | 2 个 ready BUY decision | 第二个 BUY 决策时可用现金已减去第一个的 notional |
| 66 | `test_decisions_capped_at_50` | 循环产出 100 个 decision | `last_decisions` 长度 ≤ 50 |
| 67 | `test_record_order_result_updates_counts` | 连续记录 3 个 filled order | `order_count=3` |
| 68 | `test_record_order_result_partial_fill_counts` | `status="partial_filled"` | `order_count` +1, PnL 追踪 |
| 69 | `test_logs_capped_at_500` | 写入 600 条日志 | `logs` 长度 ≤ 500 |
| 70 | `test_cycle_count_increments` | 调用 3 次 `build_order_decisions` | `cycle_count=3` |
| 71 | `test_signal_count_accumulates` | 每次 strategy_result 包含不同数量 signals | `signal_count` 正确累加 |
| 72 | `test_mark_loop_updates_state` | `mark_loop(running=True, next_run_at="...")` | `loop_running=True`, `next_run_at` 设置正确 |
| 73 | `test_mark_loop_clears_next_run` | `mark_loop(running=False)` | `loop_running=False`, `next_run_at=""` |

---

### 1.6 `update_config()` 合并

| # | 测试用例 | 操作 | 期望 |
|---|---------|------|------|
| 74 | `test_update_config_merge_partial` | `update_config({"scan_interval_seconds": 60})` | `config.scan_interval_seconds=60`，其他字段不变 |
| 75 | `test_update_config_blocks_real_trading` | `update_config({"real_trading_enabled": True})` | `config.real_trading_enabled` 仍为 `False` |
| 76 | `test_update_config_logs_event` | 任意 update | engine logs 包含 "config_updated" 事件 |

---

## 二、`core/crypto_paper_broker.py` — 模拟盘券商

**文件**: `tests/test_crypto_paper_broker.py`（新建）

**依赖**: 持久化测试需要 `tmp_path` fixture（pytest 内置），其余可直接实例化

---

### 2.1 初始化

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 77 | `test_init_defaults` | `config=None` | `broker_name="CryptoPaperBroker"`, `quote_currency="USDT"`, `initial_cash=10000`, `cash=10000`, `fee_rate=0.001`, `slippage_rate=0.0005` |
| 78 | `test_init_custom_config` | `{"initial_cash": 50000, "fee_rate": 0.002}` | `initial_cash=50000`, `cash=50000`, `fee_rate=0.002` |
| 79 | `test_init_persistence_disabled_without_path` | `storage_path=""` | `persistence_enabled=False`, `_persistence_ready=False` |
| 80 | `test_init_logs_initial_event` | 任何正常初始化 | `paper_logs` 非空，第一条 event 为 "account_initialized" 或 "account_restored" |
| 81 | `test_init_equity_curve_first_point` | 初始化后 | `equity_curve` 长度 ≥ 1，包含 "account_initialized" reason |
| 82 | `test_init_cash_equals_initial_cash` | 初始化后 | `cash == initial_cash` |
| 83 | `test_init_positions_empty` | 初始化后 | `positions == {}` |
| 84 | `test_init_orders_empty` | 初始化后 | `orders == {}` |

---

### 2.2 `place_order()` — 订单验证（拒绝场景）

所有测试使用默认 config（`initial_cash=10000`, `max_order_notional=2000`, `fee_rate=0.001`）。

| # | 测试用例 | 参数 | 期望 `order.status` | 期望 `order.message` 包含 |
|---|---------|------|--------------------|--------------------------|
| 85 | `test_reject_paper_order_disabled` | `config.paper_order_enabled=False` 后下单 | `"rejected"` | "paper order switch is disabled" |
| 86 | `test_reject_real_trading_enabled` | `config.real_trading_enabled=True` 后下单 | `"rejected"` | "refuses real_trading_enabled" |
| 87 | `test_reject_empty_symbol` | `symbol=""` | `"rejected"` | — |
| 88 | `test_reject_bad_action` | `action="HOLD"` | `"rejected"` | "unsupported action" |
| 89 | `test_reject_zero_quantity` | `quantity=0` | `"rejected"` | "quantity must be greater than 0" |
| 90 | `test_reject_negative_quantity` | `quantity=-1` | `"rejected"` | "quantity must be greater than 0" |
| 91 | `test_reject_zero_price` | `price=0` | `"rejected"` | "price must be greater than 0" |
| 92 | `test_reject_negative_price` | `price=-100` | `"rejected"` | "price must be greater than 0" |
| 93 | `test_reject_exceeds_max_notional` | `price=50000`, `quantity=1` (notional=50000 > max=2000) | `"rejected"` | "exceeds" |
| 94 | `test_reject_insufficient_cash` | `price=20000`, `quantity=1` (cost=20000+fee > cash=10000) | `"rejected"` | "insufficient USDT cash" |
| 95 | `test_reject_sell_without_position` | `action="SELL"`, `symbol="BTC/USDT"`, `quantity=0.1` (无持仓) | `"rejected"` | "insufficient crypto position; short selling is disabled" |
| 96 | `test_reject_max_position_ratio` | 多次买入直到 `market_value / equity > 0.5` | `"rejected"` | "max position ratio exceeded" |

---

### 2.3 `place_order()` — 订单成交（成功场景）

| # | 测试用例 | 操作与断言 |
|---|---------|-----------|
| 97 | `test_buy_full_fill` | `symbol="BTC/USDT"`, `action="BUY"`, `quantity=0.02`, `price=50000` (notional=1000 < partial_fill_min_notional=3000) → `order.status="filled"`, `filled_quantity=0.02`, 持仓 quantity=0.02, 现金减少约 (1000 + fee) |
| 98 | `test_buy_partial_fill` | `symbol="BTC/USDT"`, `action="BUY"`, `quantity=0.1`, `price=50000` (notional=5000 >= 3000) → `order.status="partial_filled"`, `filled_quantity=0.06` (0.1×0.6), 剩余 0.04 |
| 99 | `test_buy_fee_calculation` | `quantity=0.02`, `price=50000`, `fee_rate=0.001` → `order.fee ≈ 1000 * 0.001 = 1.0` |
| 100 | `test_buy_slippage_buy_side` | `price=50000`, `slippage_rate=0.0005` → `filled_price = 50000 * 1.0005 = 50025` |
| 101 | `test_buy_avg_price_weighted` | 先买 0.02 @50000，再买 0.01 @51000 → `avg_price = (0.02*50000 + 0.01*51000) / 0.03 = 50333.33...` |
| 102 | `test_buy_position_available_equals_quantity` | 买入后 → `positions[symbol]["available"] == positions[symbol]["quantity"]` |
| 103 | `test_sell_full_position` | 先买 0.02，再卖 0.02 → `order.status="filled"`, 持仓归零, symbol 从 `self.positions` 中移除 |
| 104 | `test_sell_partial_position` | 先买 0.02，再卖 0.01 → `order.status="filled"`, 持仓 quantity=0.01, available=0.01 |
| 105 | `test_sell_realized_pnl_profit` | 买入 @50000 (滑点后 50025)，卖出 @51000 (滑点后 50974.5) → `realized_pnl > 0` |
| 106 | `test_sell_realized_pnl_loss` | 买入 @50000，卖出 @49000 → `realized_pnl < 0` |
| 107 | `test_sell_slippage_sell_side` | 卖出 `price=50000`, `slippage_rate=0.0005` → `filled_price = 50000 * (1 - 0.0005) = 49975` |
| 108 | `test_buy_updates_last_price` | 买入后 → `positions[symbol]["last_price"]` 等于成交价 |
| 109 | `test_buy_defaults_stop_loss_take_profit` | 不传 sl/tp → `positions[symbol]["stop_loss_price"] = fill_price * 0.98`, `take_profit_price = fill_price * 1.04` |

---

### 2.4 `cancel_order()` — 撤单

| # | 测试用例 | 操作 | 期望 |
|---|---------|------|------|
| 110 | `test_cancel_pending_order` | 下 partial fill 订单 → `cancel_order(order_id)` | 返回 `True`, `order.status="cancelled"` |
| 111 | `test_cancel_partial_filled_order` | partial_filled 订单 → `cancel_order(order_id)` | 返回 `True` |
| 112 | `test_cancel_nonexistent_order` | `cancel_order("non-existent-id")` | 返回 `False` |
| 113 | `test_cancel_already_filled_order` | 已完全成交 → `cancel_order` | 返回 `False` |
| 114 | `test_cancel_already_cancelled_order` | 已取消 → 再次 `cancel_order` | 返回 `False` |
| 115 | `test_cancel_already_rejected_order` | 已拒绝 → `cancel_order` | 返回 `False` |

---

### 2.5 `get_account_info()` — 账户查询

| # | 测试用例 | 前提 | 期望 |
|---|---------|------|------|
| 116 | `test_account_initial_equity_equals_cash` | 初始化后 | `equity == cash == initial_cash == 10000` |
| 117 | `test_account_equity_includes_market_value` | 买入 BTC 后 | `equity ≈ cash + market_value` |
| 118 | `test_account_total_profit` | 买入后价格不变 → 清仓 | `total_profit < 0`（亏损手续费和滑点） |
| 119 | `test_account_total_return_percent` | `total_profit = -50`, `initial_cash=10000` | `total_return_percent ≈ -0.5` |
| 120 | `test_account_total_trades_count` | 3 笔成交记录 | `total_trades == 3` |
| 121 | `test_account_total_fee_accumulates` | 2 笔订单各 fee=1.0 | `total_fee == 2.0` |
| 122 | `test_account_positions_included` | 持有 BTC | `positions` 列表包含该币种 |

---

### 2.6 `get_positions()` — 持仓查询

| # | 测试用例 | 前提 | 期望 |
|---|---------|------|------|
| 123 | `test_empty_positions` | 初始化后 | 返回空列表 `[]` |
| 124 | `test_position_fields_complete` | 买入后 | 每条 position 包含 symbol, quantity, available, avg_price, current_price, market_value, cost_basis, unrealized_pnl, unrealized_pnl_percent |
| 125 | `test_position_unrealized_pnl` | 买入 @50000, `last_price` 未变 | `unrealized_pnl == 0` |
| 126 | `test_position_zero_quantity_filtered` | `quantity=0` 的持仓 | 不出现在结果中 |
| 127 | `test_position_current_price_equals_last_price` | 买入后 | `current_price == avg_price`（未更新行情时） |
| 128 | `test_positions_sorted_by_symbol` | 持有 BTC, ETH, SOL | 结果按 symbol 字母序排列 |

---

### 2.7 `get_orders()` — 订单分页与筛选

| # | 测试用例 | 前提 | 期望 |
|---|---------|------|------|
| 129 | `test_orders_pagination` | 10 个订单, `limit=3, offset=2` | `items` 长度=3, `total=10`, `count=3` |
| 130 | `test_orders_filter_by_status` | mixed statuses, `status="filled"` | 只返回 `filled` 订单 |
| 131 | `test_orders_sorted_by_time_desc` | 多个订单不同时间 | 最新的排在最前面 |
| 132 | `test_orders_offset_beyond_total` | 10 个订单, `offset=20` | `items` 为空, `total=10`, `count=0` |
| 133 | `test_orders_limit_clamped` | `limit=0` → `1`; `limit=1000` → `500` | 钳制在 [1, 500] |

---

### 2.8 `get_equity_curve()` 和 `get_paper_logs()`

| # | 测试用例 | 操作 | 期望 |
|---|---------|------|------|
| 134 | `test_equity_curve_returns_recent` | 2000 个权益点 → `get_equity_curve(limit=100)` | 返回最后 100 个 |
| 135 | `test_equity_curve_limit_clamped` | `limit=0` → `1`; `limit=9999` → `1000` | 钳制在 [1, 1000] |
| 136 | `test_paper_logs_limit_clamped` | `limit=0` → `1`; `limit=9999` → `500` | 钳制在 [1, 500] |

---

### 2.9 持久化 — 存储与恢复

> 使用 `tmp_path` fixture 创建临时数据库文件。

| # | 测试用例 | 操作 | 期望 |
|---|---------|------|------|
| 137 | `test_persist_account_basic` | 创建 broker (with `storage_path=tmp_path/db`) → 下单 → 创建第二个 broker 实例加载同一 DB | `initial_cash`, `cash`, `broker_name`, `quote_currency` 完全恢复 |
| 138 | `test_persist_orders_restored` | 5 笔不同状态订单 → 重新加载 | `orders` 全部恢复, status/quantity/fee 一致 |
| 139 | `test_persist_positions_restored` | 买入 3 个不同币种 → 重新加载 | positions 全部恢复, avg_price/quantity 一致 |
| 140 | `test_persist_trade_history_restored` | 多笔成交 → 重新加载 | `trade_history` 全部恢复 |
| 141 | `test_persist_equity_curve_dedup` | 多次下单 → 重新加载 | `equity_curve` 条目不重复（通过 timestamp+order_id+reason 去重） |
| 142 | `test_persist_logs_dedup` | 重新加载同一 DB 两次 | `paper_logs` 条目不重复（通过 5 元组去重） |
| 143 | `test_prune_persisted_logs` | 写入 6000 条日志 (`max_persisted_log_entries=5000`) | DB 中 `crypto_paper_logs` 表 ≤ 5000 条 |
| 144 | `test_persist_no_storage_path` | `storage_path=""` → `_persist_state()` | 不抛异常, `persistence_enabled=False` |
| 145 | `test_restore_from_empty_db` | 空 DB 文件 | `_load_state()` 返回 `False`, 使用默认值 |

---

### 2.10 边界情况

| # | 测试用例 | 条件 | 期望 |
|---|---------|------|------|
| 146 | `test_quantity_precision_rounding` | `quantity_precision=2`, `quantity=0.005` | `order.quantity=0.01` |
| 147 | `test_price_precision_rounding` | `price_precision=2`, `price=50000.005` | `order.price=50000.01` |
| 148 | `test_order_id_unique` | 连续下 100 单 | 所有 `order_id` 不重复 |
| 149 | `test_equity_curve_capped_at_1000` | 写入 2000 个权益点 | `equity_curve` 长度 = 1000 |
| 150 | `test_logs_capped` | 写入 (`max_log_entries` + 100) 条日志 | `paper_logs` 长度 ≤ max_log_entries |
| 151 | `test_symbol_normalized_with_quote` | `symbol="BTC"`, `quote_currency="USDT"` | `order.symbol == "BTC/USDT"` |
| 152 | `test_symbol_already_has_slash` | `symbol="BTC/USDT"` | 保持 `"BTC/USDT"` |
| 153 | `test_reject_order_logs_event` | 任何被拒绝的订单 | `paper_logs` 包含 "order_rejected" 事件, level="WARN" |
| 154 | `test_filled_order_logs_event` | 成交订单 | `paper_logs` 包含 "order_filled" 或 "order_partially_filled" 事件 |
| 155 | `test_equity_curve_recorded_on_fill` | 成交后 | `equity_curve` 新增一条记录, reason=order.status |
| 156 | `test_equity_curve_recorded_on_reject` | 拒绝后 | `equity_curve` 新增一条记录, reason="order_rejected" |
| 157 | `test_partial_fill_remaining_quantity` | partial_filled 订单 | order.message 含 `filled_quantity/total` 格式 |
| 158 | `test_cancel_releases_no_cash` | 取消 pending 订单 | cash 不变（未成交） |

---

## 三、`api/services/crypto_service.py` — 加密行情与交易服务

**文件**: `tests/test_crypto_service.py`（新建）

**依赖**: 需要使用 `unittest.mock.patch` 或 `pytest.MonkeyPatch` 来 mock 子组件：
- `self.provider`（`CryptoMarketDataProvider`）
- `self.market_cache`（`CryptoMarketCache`）
- `self.ai_advisor`（`AiSignalAdvisor`）
- `self.ai_store`（`AiSignalStore`）
- `self.macro_provider`（`MacroDataProvider`）

> 推荐 mock 策略：创建一个 helper 函数来构造带有 mock 子组件的 `CryptoService` 实例。

```python
from unittest.mock import MagicMock, patch

def _make_service(config=None, **mock_overrides):
    """创建 CryptoService，所有子组件均为 MagicMock。"""
    config = config or {"crypto": {"symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"]}}
    with patch("api.services.crypto_service.CryptoMarketDataProvider") as mock_provider_cls, \
         patch("api.services.crypto_service.CryptoMarketCache") as mock_cache_cls, \
         patch("api.services.crypto_service.CryptoPaperBrokerExecutor") as mock_broker_cls, \
         patch("api.services.crypto_service.CryptoStrategyEngine") as mock_strategy_cls, \
         patch("api.services.crypto_service.AutoTradingEngine") as mock_auto_cls, \
         patch("api.services.crypto_service.ShadowTradingEngine") as mock_shadow_cls, \
         patch("api.services.crypto_service.MacroDataProvider") as mock_macro_cls, \
         patch("api.services.crypto_service.MacroRiskEvaluator") as mock_macro_eval_cls, \
         patch("api.services.crypto_service.AiSignalAdvisor") as mock_ai_cls, \
         patch("api.services.crypto_service.AiSignalStore") as mock_ai_store_cls, \
         patch("api.services.crypto_service.AuditLogger") as mock_audit_cls, \
         patch("api.services.crypto_service.BinanceTestnetExecutor") as mock_testnet_cls:
        service = CryptoService(config)
        return service
```

---

### 3.1 初始化

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 159 | `test_init_default_symbols` | `config={"crypto": {"symbols": ["BTC/USDT", "ETH/USDT"]}}` | `default_symbols == ["BTC/USDT", "ETH/USDT"]` |
| 160 | `test_init_symbols_normalized` | `config={"crypto": {"symbols": ["btc/usdt"]}}` | `default_symbols == ["BTC/USDT"]` |
| 161 | `test_init_default_symbols_dedup` | `config={"crypto": {"symbols": ["BTC/USDT", "BTC/USDT"]}}` | `default_symbols` 中无重复 |
| 162 | `test_init_all_sub_components_created` | 正常 config | `provider`, `market_cache`, `paper_broker`, `strategy_engine`, `auto_trading_engine`, `shadow_engine`, `macro_evaluator`, `ai_advisor`, `ai_store` 全部非 None |
| 163 | `test_init_auto_config_inherits_risk_max_notional` | `config={"risk": {"max_order_notional": 500}}` | `auto_trading_engine.config.max_order_notional == 500` |
| 164 | `test_init_macro_cache_initial_none` | 初始化后 | `_macro_cache is None`, `_macro_cache_time == 0.0` |
| 165 | `test_init_auto_scan_lock_is_asyncio_lock` | 初始化后 | `isinstance(_auto_scan_lock, asyncio.Lock)` |

---

### 3.2 `get_quotes()` — 行情查询

> 需要 mock `self.provider.fetch_quotes`、`self.provider.fetch_all_tickers`、`self.market_cache.get_quotes`、`self.market_cache.upsert_quotes`。

| # | 测试用例 | 行为 | 期望 |
|---|---------|------|------|
| 166 | `test_quotes_with_specific_symbols` | `symbols=["BTC/USDT", "ETH/USDT"]`; mock `fetch_quotes` 返回 2 条 | `items` 长度=2, `source="ccxt"` |
| 167 | `test_quotes_empty_symbols_list` | `symbols=[]` | `items=[]`, `count=0` |
| 168 | `test_quotes_null_symbols_calls_fetch_all` | `symbols=None`; mock `fetch_all_tickers` 返回数据 | 调用 `fetch_all_tickers` 而非 `fetch_quotes` |
| 169 | `test_quotes_search_filters_correctly` | `search="BTC"`; mock 返回 [BTC, ETH, SOL] | 只返回 symbol 含 "BTC" 的项 |
| 170 | `test_quotes_search_case_insensitive` | `search="btc"`; mock 返回 [BTC] | 仍然匹配 |
| 171 | `test_quotes_pagination` | `limit=2, offset=1`; mock 返回 5 条 | `items` 长度=2, `total=5`, `count=2` |
| 172 | `test_quotes_pagination_defaults` | 不传 limit/offset | `limit=0, offset=0` → 返回全部 |
| 173 | `test_quotes_fallback_to_cache` | mock `fetch_quotes` 抛异常; mock `market_cache.get_quotes` 返回缓存数据 | `source="cache_binance"`, 返回缓存数据 |
| 174 | `test_quotes_no_cache_no_source_raises` | mock `fetch_quotes` 抛异常; `market_cache.get_quotes` 返回 `[]` | 抛出 `ApiError(503)` |
| 175 | `test_quotes_records_snapshots_to_cache` | mock `fetch_quotes` 成功 | `market_cache.upsert_quotes` 被调用 |
| 176 | `test_quotes_cache_fallback_only_for_specific_symbols` | `symbols=["BTC"]` + mock 抛异常; cache 有 BTC 数据 | 返回缓存数据（不会为 None symbols 走 cache fallback 导致 503） |

---

### 3.3 `get_available_symbols()` — 交易对发现

> 需要 mock `self.market_cache.get_symbols`、`self.market_cache.upsert_exchange_info`、`self.provider.load_markets`。

| # | 测试用例 | 行为 | 期望 |
|---|---------|------|------|
| 177 | `test_symbols_from_cache` | mock `get_symbols` 返回 `([{...}], 400)` | 直接返回缓存, 不调用 `provider.load_markets` |
| 178 | `test_symbols_cache_miss_loads_markets` | mock `get_symbols` 返回 `([], 0)`; mock `load_markets` 返回 dict | 调用 `load_markets` → `upsert_exchange_info` → 再次 `get_symbols` |
| 179 | `test_symbols_cache_miss_load_markets_fails` | `load_markets` 也抛异常 | `CryptoSymbolListResponse` items=[], total=0, 不崩溃 |
| 180 | `test_symbols_pagination_passed_through` | `limit=50, offset=100` | 参数正确传给 `market_cache.get_symbols` |
| 181 | `test_symbols_quote_filter_passed_through` | `quote="USDT"` | 参数正确传给 `market_cache.get_symbols` |
| 182 | `test_symbols_search_passed_through` | `search="BTC"` | 参数正确传给 `market_cache.get_symbols` |

---

### 3.4 `get_klines()` — K线查询

> 需要 mock `self.provider.fetch_ohlcv`、`self.market_cache.get_klines`、`self.market_cache.upsert_klines`。

| # | 测试用例 | 行为 | 期望 |
|---|---------|------|------|
| 183 | `test_klines_invalid_symbol_raises` | `symbol=""` | 抛出 `ApiError(400)` |
| 184 | `test_klines_success` | mock `fetch_ohlcv` 返回 K线 | 返回 `CryptoKLinesResponse`, source=exchange name |
| 185 | `test_klines_fallback_to_cache` | mock `fetch_ohlcv` 抛异常; cache 有数据 | `source="cache_binance"`, 返回缓存数据 |
| 186 | `test_klines_no_cache_no_source_raises` | mock `fetch_ohlcv` 抛异常; cache 无数据 | 抛出 `ApiError(503)` |
| 187 | `test_klines_bad_period_caught` | mock `fetch_ohlcv` 抛 `ValueError("invalid period")` | 抛出 `ApiError(400)` |
| 188 | `test_klines_records_to_cache` | mock `fetch_ohlcv` 成功 | `market_cache.upsert_klines` 被调用 |

---

### 3.5 `get_orderbook()` — 订单簿

> 需要 mock `self.provider.fetch_order_book`。

| # | 测试用例 | 行为 | 期望 |
|---|---------|------|------|
| 189 | `test_orderbook_invalid_symbol` | `symbol=""` | 抛出 `ApiError(400)` |
| 190 | `test_orderbook_success` | mock `fetch_order_book` 返回 bids/asks | 返回 `CryptoOrderBookResponse` |
| 191 | `test_orderbook_provider_error` | mock 抛异常 | 抛出 `ApiError(503)` |

---

### 3.6 模拟盘操作（使用真实 `CryptoPaperBrokerExecutor`）

> 这部分不需要 mock，直接使用真实的 broker 测试。

| # | 测试用例 | 操作 | 期望 |
|---|---------|------|------|
| 192 | `test_place_paper_order_buy` | `place_paper_order(CryptoPaperOrderRequest(symbol="BTC/USDT", action="BUY", quantity=0.01, price=50000))` | 返回 `CryptoPaperOrderResponse`, status="filled"（notional=500 < 2000） |
| 193 | `test_place_paper_order_sell_no_position_rejected` | `action="SELL"`, 无持仓 | 返回 status="rejected" |
| 194 | `test_get_paper_orders_pagination` | 下 5 单 → `get_paper_orders(limit=2, offset=1)` | `count=2`, `total=5` |
| 195 | `test_cancel_paper_order_success` | 下单 → `cancel_paper_order(order_id)` | `{"success": True}` |
| 196 | `test_cancel_paper_order_nonexistent` | `cancel_paper_order("bad-id")` | `{"success": False}` |
| 197 | `test_get_paper_account_initial` | 初始化后 | `initial_cash=10000`, `equity=10000` |
| 198 | `test_get_paper_positions_after_buy` | 买入后 | positions 长度 ≥ 1, total_market_value > 0 |
| 199 | `test_get_equity_curve` | 下单后 | 返回非空列表 |
| 200 | `test_get_paper_logs` | 操作后 | 返回非空列表 |

---

### 3.7 自动交易控制

> 需要 mock `self.auto_trading_engine` 和 `self.provider`。

| # | 测试用例 | 操作 | 期望 |
|---|---------|------|------|
| 201 | `test_start_auto_trading` | `start_auto_trading()` | engine state="running", `_auto_loop_task` 非 None |
| 202 | `test_pause_auto_trading` | start → `pause_auto_trading()` | engine state="paused", `_auto_loop_task` 为 None |
| 203 | `test_stop_auto_trading` | start → `stop_auto_trading()` | engine state="stopped" |
| 204 | `test_get_auto_trading_status` | 调用 `get_auto_trading_status()` | 返回 `AutoTradingStatusResponse`, 包含 engine status 所有字段 |
| 205 | `test_update_auto_trading_config` | `update_auto_trading_config(AutoTradingConfigRequest(...))` | engine 收到 `update_config` 调用 |
| 206 | `test_get_auto_trading_logs` | 调用 `get_auto_trading_logs(limit=50)` | 返回 `AutoTradingLogsResponse`, `count` ≤ 50 |

---

### 3.8 AI 信号

> 需要 mock `self.ai_advisor`、`self.ai_store`。

| # | 测试用例 | 行为 | 期望 |
|---|---------|------|------|
| 207 | `test_analyze_ai_signal_hold` | mock `ai_advisor.analyze` 返回 `{"action": "HOLD", "confidence": 0.8}` | `approval_status="blocked"`, reason 含 "HOLD" |
| 208 | `test_analyze_ai_signal_low_confidence` | confidence=0.3 < min_confidence_for_order=0.65 | `approval_status="blocked"` |
| 209 | `test_analyze_ai_signal_buy_approved` | action="BUY", confidence=0.8, suggested_notional=200 | `approval_status="approved"` |
| 210 | `test_analyze_ai_signal_sell_no_position` | action="SELL", `_position_quantity` 返回 0 | `approval_status="blocked"`, "no position to sell" |
| 211 | `test_analyze_ai_signal_invalid_model_output` | `ai_advisor.analyze` 抛 `ValueError` | 捕获并保存为 failed signal, `approval_status="failed"` |
| 212 | `test_analyze_ai_signal_provider_unavailable` | `ai_advisor.analyze` 抛 `Exception` | 抛出 `ApiError(503, AI_PROVIDER_UNAVAILABLE)` |
| 213 | `test_list_ai_signals` | mock `ai_store.list_signals` 返回分页数据 | 返回 `AiSignalListResponse`, 分页字段正确 |
| 214 | `test_get_ai_signal_found` | mock `ai_store.get_signal` 返回记录 | 返回 `AiSignalRecordResponse` |
| 215 | `test_get_ai_signal_not_found` | mock `ai_store.get_signal` 返回 None | 抛出 `ApiError(404)` |

---

### 3.9 宏观风险检查

> 需要 mock `self.macro_provider` 和 `self.macro_evaluator`。

| # | 测试用例 | 行为 | 期望 |
|---|---------|------|------|
| 216 | `test_macro_overview_cache_hit` | 第一次调用 → 再次调用（间隔 < 300s） | 两次返回相同对象（缓存命中） |
| 217 | `test_macro_overview_cache_expired` | 第一次调用 → 手动设 `_macro_cache_time -= 301` → 第二次调用 | 返回新对象（缓存过期） |
| 218 | `test_macro_overview_first_call_no_cache` | `_macro_cache is None` | 调用 `macro_provider.fetch_snapshot` 和 `macro_evaluator.evaluate` |

---

### 3.10 `get_connection_health()` — 连接健康

| # | 测试用例 | 行为 | 期望 |
|---|---------|------|------|
| 219 | `test_connection_health_delegates` | 调用 `get_connection_health()` | 返回 `ConnectionHealthResponse`，数据来自 `provider.get_connection_health()` |

---

### 3.11 `_assess_ai_advice()` — AI 审批（纯逻辑，不需要 mock）

> 直接调用 `service._assess_ai_advice(advice, account, positions)`。

| # | 测试用例 | 条件 | 期望 |
|---|---------|------|------|
| 220 | `test_ai_blocked_real_trading_any_flag` | `account={"real_trading_enabled": True}` | `approval_status="blocked"` |
| 221 | `test_ai_blocked_risk_real_trading` | `config={"risk": {"real_trading_enabled": True}}` | `approval_status="blocked"` |
| 222 | `test_ai_blocked_trading_real_trading` | `config={"trading": {"real_trading_enabled": True}}` | `approval_status="blocked"` |
| 223 | `test_ai_blocked_hold` | `advice={"action": "HOLD", "confidence": 0.8}` | `approval_status="blocked"`, reason 含 "HOLD" |
| 224 | `test_ai_blocked_bad_action` | `advice={"action": "TRANSFER"}` | `approval_status="blocked"`, "unsupported AI action" |
| 225 | `test_ai_blocked_low_confidence` | `confidence=0.3`, `min_confidence_for_order=0.65` | `approval_status="blocked"` |
| 226 | `test_ai_blocked_leverage_enabled` | `config={"risk": {"allow_leverage": True}}` | `approval_status="blocked"` |
| 227 | `test_ai_blocked_short_selling_enabled` | action="SELL", `config={"risk": {"allow_short_selling": True}}` | `approval_status="blocked"` |
| 228 | `test_ai_blocked_zero_notional` | `suggested_notional_usdt=0` | `approval_status="blocked"`, "notional is zero" |
| 229 | `test_ai_buy_capped_to_available_cash` | action="BUY", `suggested_notional=500`, `account={"available_cash": 200}`, `max_order_notional=300` | `approved_notional_usdt=200` |
| 230 | `test_ai_buy_capped_to_max_order` | action="BUY", `suggested_notional=500`, `available_cash=1000`, `max_order_notional=300` | `approved_notional_usdt=300` |
| 231 | `test_ai_buy_insufficient_cash` | action="BUY", `account={"available_cash": 0}`, `max_order_notional=300` | `approval_status="blocked"`, "insufficient USDT cash" |
| 232 | `test_ai_sell_no_position` | action="SELL", `positions=[]` | `approval_status="blocked"`, "no position to sell" |
| 233 | `test_ai_sell_approved` | action="SELL", `suggested_notional=500`, `positions=[{"symbol": "BTC/USDT", "available": 0.1}]`, 当前价格=50000 | `approval_status="approved"` |
| 234 | `test_ai_notional_capped_by_paper_max` | `paper_config={"max_order_notional": 100}`, `suggested_notional=500` | `max_order` 被限制为 100 |
| 235 | `test_ai_notional_capped_by_risk_max` | `risk_config={"max_order_notional": 150}`, `suggested_notional=500` | `max_order` 被限制为 150 |

---

### 3.12 `_normalize_symbols()` — 符号归一化

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 236 | `test_normalize_symbols_uppercase` | `["btc/usdt"]` | `["BTC/USDT"]` |
| 237 | `test_normalize_symbols_dedup` | `["BTC/USDT", "BTC/USDT"]` | `["BTC/USDT"]` |
| 238 | `test_normalize_symbols_filters_invalid` | `["", "BTC/USDT"]` | `["BTC/USDT"]`（空字符串被过滤） |

---

### 3.13 `_position_quantity()` — 持仓数量查询

| # | 测试用例 | 输入 | 期望 |
|---|---------|------|------|
| 239 | `test_position_quantity_found` | `positions=[{"symbol": "BTC/USDT", "available": 1.5}]` | 返回 `1.5` |
| 240 | `test_position_quantity_fallback_to_quantity` | `positions=[{"symbol": "BTC/USDT", "quantity": 2.0}]`（无 available 字段） | 返回 `2.0` |
| 241 | `test_position_quantity_not_found` | `positions=[]` | 返回 `0.0` |
| 242 | `test_position_quantity_symbol_normalized` | `positions=[{"symbol": "btc/usdt", "available": 1.0}]`; 查询 `symbol="BTC/USDT"` | 返回 `1.0`（归一化匹配） |

---

## 汇总

| 模块 | 文件 | 测试用例数 | 需要 mock | 优先级 |
|------|------|-----------|----------|--------|
| `auto_trading_engine.py` | 扩充 `tests/test_auto_trading.py` | 76 个 | 否 | 🔴 P0 |
| `crypto_paper_broker.py` | 新建 `tests/test_crypto_paper_broker.py` | 82 个 | 仅持久化测试用 `tmp_path` | 🔴 P0 |
| `crypto_service.py` | 新建 `tests/test_crypto_service.py` | 84 个 | 是（`unittest.mock`） | 🔴 P0 |
| **合计** | | **242 个** | | |

---

## 实施注意事项

1. **`crypto_paper_broker` 持久化测试**：使用 pytest 内置的 `tmp_path` fixture 创建临时 SQLite 文件路径，测试结束后自动清理。

2. **`crypto_service` mock 策略**：由于 `CryptoService.__init__` 会创建大量子组件，建议在测试模块顶层用 `patch.multiple` 批量替换所有子组件的构造器，或写一个 `_make_mock_service()` 辅助函数。

3. **异步测试**：`crypto_service` 中约一半方法是 `async`，需要使用 `pytest-asyncio`（`pip install pytest-asyncio`）并在测试函数上加 `@pytest.mark.asyncio` 装饰器。

4. **所有拒绝路径都要测**：`DecisionPipeline` 的 8 步门控和 `CryptoPaperBrokerExecutor._validate_order` 的 8 种拒绝原因，每一步/每种都必须有独立的断言。

5. **数值精度**：涉及金额计算的断言使用 `pytest.approx(expected, rel=1e-6)` 而非 `==`，避免浮点误差导致 CI 不稳定。

6. **运行命令**：
   ```bash
   pytest tests/test_auto_trading.py tests/test_crypto_paper_broker.py tests/test_crypto_service.py -v
   ```
