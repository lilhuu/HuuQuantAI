# auto_trader 改进实施路线图

> 基于与 CryptoQuant AI 的对比分析，分 3 个阶段、15 个步骤实施

---

## 第一阶段：回测系统升级（优先级 🔴）

### 步骤 1：新建 `core/walk_forward_backtest.py`

目的：将单段回测升级为 Walk-Forward 回测框架

核心内容：
```python
# core/walk_forward_backtest.py

from dataclasses import dataclass, field
from typing import Any
from core.crypto_strategy_engine import CryptoStrategyEngine

@dataclass
class WalkForwardConfig:
    train_ratio: float = 0.6          # 训练集占比
    validation_ratio: float = 0.2     # 验证集占比
    test_ratio: float = 0.2           # 测试集占比
    min_train_candles: int = 50       # 最少训练K线数
    step_size: int = 20               # 窗口滑动步长
    perturbation_runs: int = 200      # 扰动分析次数
    perturbation_pct: float = 0.025   # 初始资金扰动幅度

@dataclass
class WalkForwardRound:
    round_index: int
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    strategy_id: str
    symbol: str
    params: dict
    train_metrics: dict
    validation_metrics: dict
    is_fragile: bool = False          # 扰动分析:训练/验证差异过大

def create_walk_forward_windows(klines, config: WalkForwardConfig):
    """将K线数据切分为训练/验证/测试窗口"""
    total = len(klines)
    min_needed = config.min_train_candles * 2
    windows = []
    start = 0
    round_idx = 0
    while start + min_needed <= total:
        train_end = start + int((total - start) * config.train_ratio)
        val_end = train_end + int((total - start) * config.validation_ratio)
        windows.append({
            "round_index": round_idx,
            "train": klines[start:train_end],
            "validation": klines[train_end:val_end],
            "test": klines[val_end:] if val_end < total else [],
            "train_start": klines[start]["start_time"],
            "train_end": klines[train_end - 1]["start_time"],
            "validation_start": klines[train_end]["start_time"],
            "validation_end": klines[min(val_end, total) - 1]["start_time"],
        })
        start += config.step_size
        round_idx += 1
    return windows

def run_walk_forward(engine: CryptoStrategyEngine, klines_by_symbol, config, param_grid):
    """对每个参数组合在每轮窗口上运行回测,选出验证集最优参数"""
    # 伪代码结构:
    # for each symbol, strategy:
    #   windows = create_walk_forward_windows(klines)
    #   for each param_combo in param_grid:
    #     for each window:
    #       train_result = engine.backtest(train_data, param_combo)
    #       val_result = engine.backtest(val_data, param_combo)
    #       score = val_result.total_return - 2 * val_result.max_drawdown
    #   best_params = argmax(average_score across windows)
    #   perturbation_check(best_params)  # 200次 ±2.5%初始资金
    pass

def build_strict_factor_audit():
    """因子审计:标记哪些数据在回测中point-in-time不可用"""
    return {
        "price": {"available": True, "source": "ohlcv_timestamp_only"},
        "macro": {"available": False, "reason": "no_point_in_time_macro_data"},
        "onchain": {"available": False, "reason": "no_onchain_data_source"},
        "news": {"available": False, "reason": "no_news_sentiment_source"},
        "orderbook": {"available": False, "reason": "no_historical_orderbook"},
    }
```

涉及的文件:
- 新建: `core/walk_forward_backtest.py` (~300行)
- 新建: `tests/test_walk_forward.py`

---

### 步骤 2：改造 `CryptoStrategyEngine.backtest()` 支持参数网格

在现有 `core/crypto_strategy_engine.py` 的 `backtest` 方法上增加:

```python
# 在 CryptoStrategyEngine 类中新增方法

def build_param_grid(self, strategy_type: str) -> list[dict]:
    """为每个策略类型生成参数网格"""
    grids = {
        "dual_ma": [
            {"fast_period": 5, "slow_period": 20},
            {"fast_period": 7, "slow_period": 25},
            {"fast_period": 10, "slow_period": 30},
        ],
        "rsi": [
            {"rsi_period": 14, "oversold": 25, "overbought": 75},
            {"rsi_period": 14, "oversold": 30, "overbought": 70},
            {"rsi_period": 21, "oversold": 30, "overbought": 70},
        ],
        "momentum": [
            {"lookback_period": 10, "buy_threshold": 0.02, "sell_threshold": -0.02},
            {"lookback_period": 10, "buy_threshold": 0.03, "sell_threshold": -0.02},
            {"lookback_period": 20, "buy_threshold": 0.03, "sell_threshold": -0.03},
        ],
        "bollinger": [
            {"period": 20, "stddev_multiplier": 2.0},
            {"period": 20, "stddev_multiplier": 2.5},
            {"period": 14, "stddev_multiplier": 2.0},
        ],
        "macd": [
            {"fast": 12, "slow": 26, "signal_period": 9},
            {"fast": 8, "slow": 21, "signal_period": 5},
            {"fast": 5, "slow": 35, "signal_period": 5},
        ],
    }
    return grids.get(strategy_type, [{}])

def backtest_with_grid(self, market_data, configs, initial_cash=10000, fee_rate=0.001):
    """带参数网格的回测,返回每个参数组合的结果"""
    results = []
    for config in configs:
        strategy_type = config.type
        param_grid = self.build_param_grid(strategy_type)
        for params in param_grid:
            merged_config = config
            merged_config.parameters = {**config.parameters, **params}
            # 运行回测,收集结果
            result = self.backtest(market_data, [merged_config], initial_cash, fee_rate)
            results.append({
                "strategy_id": config.strategy_id,
                "params": params,
                "result": result[0] if result else None,
            })
    return results
```

涉及的文件:
- 修改: `core/crypto_strategy_engine.py` (新增 ~80 行)

---

### 步骤 3：新增 Walk-Forward API 端点

在 `api/routers/crypto.py` 中增加:

```python
@router.post("/strategies/walk-forward", response_model=..., summary="Walk-forward backtest")
async def walk_forward_backtest(
    request: CryptoStrategyWalkForwardRequest,
    service: CryptoService = Depends(get_crypto_service),
):
    return await service.walk_forward_backtest(request)
```

需要新建的 Pydantic 模型 (在 `api/models/request.py`):
```python
class CryptoStrategyWalkForwardRequest(CryptoStrategyRunRequest):
    train_ratio: float = Field(default=0.6, ge=0.3, le=0.8)
    step_size: int = Field(default=20, ge=5, le=100)
    perturbation_runs: int = Field(default=200, ge=0, le=500)
    param_grid: list[dict] = Field(default_factory=list)  # 自定义参数网格
```

涉及的 文件:
- 修改: `api/routers/crypto.py` (新增 ~15 行)
- 修改: `api/models/request.py` (新增 ~10 行)
- 修改: `api/models/response.py` (新增 WalkForward 相关响应模型 ~50 行)
- 修改: `api/services/crypto_service.py` (新增方法 ~30 行)

---

## 第二阶段：交易决策管道升级（优先级 🔴）

### 步骤 4：新建 `core/macro_risk.py` — 宏观风险门控

```python
# core/macro_risk.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import aiohttp

class MacroGateLevel(Enum):
    ALLOW_FULL = "allow_full"        # 风险 < -0.10
    ALLOW_REDUCED = "allow_reduced"   # -0.30 < 风险 <= -0.10
    BLOCK_NEW = "block_new"           # 风险 <= -0.30

@dataclass
class MacroRiskConfig:
    dxy_change_threshold: float = 0.02     # DXY 30天变化阈值
    m2_change_threshold: float = 0.03      # M2 3月变化阈值
    cache_ttl_minutes: int = 60
    position_multiplier: dict = field(default_factory=lambda: {
        "allow_full": 1.0,
        "allow_reduced": 0.5,
        "block_new": 0.0,
    })

class MacroRiskEvaluator:
    """宏观风险评分器 — 基于 DXY + M2"""
    
    def __init__(self, config: MacroRiskConfig):
        self.config = config
        self._cache = {}  # 简单内存缓存
    
    async def fetch_dxy(self) -> Optional[float]:
        """从 Yahoo Finance 获取 DXY 指数"""
        # 使用 yfinance 或直接 HTTP 请求
        url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"
        # ...
        pass
    
    async def fetch_m2(self) -> Optional[float]:
        """从 FRED API 获取 M2 货币供应"""
        # FRED API: https://api.stlouisfed.org/fred/series/observations
        pass
    
    async def evaluate(self) -> dict:
        """返回宏观风险评估结果"""
        dxy_change = await self.fetch_dxy()
        m2_change = await self.fetch_m2()
        
        # 评分逻辑 (参考 CryptoQuant AI 的做法)
        score = 0.0
        if dxy_change and dxy_change > self.config.dxy_change_threshold:
            score -= 0.15  # 美元走强 → 风险资产承压
        if m2_change and m2_change < 0:
            score -= 0.10  # 流动性收缩
        
        gate = MacroGateLevel.ALLOW_FULL
        if score <= -0.30:
            gate = MacroGateLevel.BLOCK_NEW
        elif score <= -0.10:
            gate = MacroGateLevel.ALLOW_REDUCED
        
        return {
            "risk_score": round(score, 4),
            "gate_level": gate.value,
            "position_multiplier": self.config.position_multiplier[gate.value],
            "dxy_change": dxy_change,
            "m2_change": m2_change,
        }
```

涉及的文件:
- 新建: `core/macro_risk.py` (~150行)
- 修改: `requirements.txt` (增加 yfinance 依赖)
- 新建: `tests/test_macro_risk.py`

---

### 步骤 5：新建 `core/regime_detector.py` — 市场制度检测

```python
# core/regime_detector.py

from enum import Enum
from statistics import fmean, pstdev
from typing import Any

class MarketRegime(Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    RISK_OFF = "risk_off"
    UNKNOWN = "unknown"

class RegimeDetector:
    """市场制度检测器 — 复合多因子评分"""
    
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        # 各因子权重 (参考 CryptoQuant AI 的设置)
        self.weights = {
            "trend": 0.30,       # MA斜率趋势强度
            "momentum": 0.15,    # 价格动量
            "volume": 0.15,      # 成交量变化
            "orderbook": 0.15,   # 订单簿不平衡
            "funding": -0.10,    # 资金费率过热（负向）
            "volatility": -0.10, # 波动率尖峰（负向）
        }
    
    def detect(self, closes: list[float], volumes: list[float] = None,
               orderbook_imbalance: float = 0.0, funding_rate: float = 0.0) -> dict:
        """返回制度检测结果"""
        if len(closes) < 20:
            return {"regime": MarketRegime.UNKNOWN.value, "score": 0.0}
        
        scores = {}
        
        # 1. 趋势分数: MA20 斜率
        ma20 = fmean(closes[-20:])
        ma20_prev = fmean(closes[-40:-20]) if len(closes) >= 40 else closes[0]
        trend_slope = (ma20 - ma20_prev) / ma20_prev if ma20_prev > 0 else 0
        scores["trend"] = min(max(trend_slope * 100, -1), 1)
        
        # 2. 动量分数: 5日 ROC
        if len(closes) >= 6:
            roc = (closes[-1] - closes[-6]) / closes[-6]
            scores["momentum"] = min(max(roc * 50, -1), 1)
        else:
            scores["momentum"] = 0
        
        # 3. 成交量分数
        if volumes and len(volumes) >= 20:
            vol_short = fmean(volumes[-5:])
            vol_long = fmean(volumes[-20:])
            scores["volume"] = min(max((vol_short / vol_long - 1) * 5, -1), 1) if vol_long > 0 else 0
        else:
            scores["volume"] = 0
        
        # 4. 订单簿分数
        scores["orderbook"] = min(max(orderbook_imbalance * 2, -1), 1)
        
        # 5. 资金费率分数 (负向: 费率极端 → 风险)
        if abs(funding_rate) > 0.001:  # >0.1%
            scores["funding"] = min(abs(funding_rate) * 10, 1)
        else:
            scores["funding"] = 0
        
        # 6. 波动率分数 (负向)
        if len(closes) >= 20:
            returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            vol = pstdev(returns[-20:]) if len(returns) >= 20 else pstdev(returns)
            avg_vol = pstdev(returns) if len(returns) >= 40 else vol
            vol_spike = (vol / avg_vol - 1) if avg_vol > 0 else 0
            scores["volatility"] = min(max(vol_spike * 5, -1), 1)
        else:
            scores["volatility"] = 0
        
        # 加权综合分数
        composite = sum(self.weights[k] * scores.get(k, 0) for k in self.weights)
        
        # 分类
        if composite > 0.15:
            regime = MarketRegime.TREND_UP
        elif composite < -0.15:
            regime = MarketRegime.TREND_DOWN
        elif abs(composite) <= 0.15:
            regime = MarketRegime.RANGE
        else:
            regime = MarketRegime.UNKNOWN
        
        return {
            "regime": regime.value,
            "composite_score": round(composite, 4),
            "factor_scores": {k: round(v, 4) for k, v in scores.items()},
        }
```

涉及的文件:
- 新建: `core/regime_detector.py` (~120行)
- 新建: `tests/test_regime_detector.py`

---

### 步骤 6：新建 `core/decision_pipeline.py` — 多阶段决策管道

```python
# core/decision_pipeline.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from core.macro_risk import MacroRiskEvaluator, MacroGateLevel
from core.regime_detector import RegimeDetector
from core.crypto_strategy_engine import CryptoStrategyEngine
from core.crypto_paper_broker import CryptoPaperBrokerExecutor

@dataclass
class DecisionStep:
    """决策管道中的单个步骤记录"""
    step_name: str
    status: str  # "pass", "block", "skip"
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    details: dict = field(default_factory=dict)

@dataclass
class PipelineContext:
    """管道执行的上下文"""
    symbols: list[str]
    period: str
    market_data: dict  # {symbol: [klines]}
    macro_gate: MacroGateLevel
    macro_risk_score: float
    positions: list[dict]
    account_balance: float
    max_positions: int = 2
    steps: list[DecisionStep] = field(default_factory=list)

class DecisionPipeline:
    """多阶段交易决策管道"""
    
    def __init__(self, engine: CryptoStrategyEngine, broker: CryptoPaperBrokerExecutor,
                 regime_detector: RegimeDetector, macro_evaluator: MacroRiskEvaluator):
        self.engine = engine
        self.broker = broker
        self.regime_detector = regime_detector
        self.macro_evaluator = macro_evaluator
    
    def add_step(self, ctx: PipelineContext, name: str, status: str, reason: str, **details):
        ctx.steps.append(DecisionStep(step_name=name, status=status, reason=reason, details=details))
    
    async def run(self, symbols: list[str], period: str, market_data: dict,
                  strategy_configs: list) -> PipelineContext:
        ctx = PipelineContext(symbols=symbols, period=period, market_data=market_data, ...)
        
        # === 阶段 1: 宏观门控 ===
        macro = await self.macro_evaluator.evaluate()
        ctx.macro_gate = MacroGateLevel(macro["gate_level"])
        ctx.macro_risk_score = macro["risk_score"]
        if ctx.macro_gate == MacroGateLevel.BLOCK_NEW:
            self.add_step(ctx, "macro_gate", "block", "宏观风险过高,阻止新开仓", macro=macro)
            return ctx  # 直接返回,不进行后续步骤
        self.add_step(ctx, "macro_gate", "pass", f"宏观门控通过: {ctx.macro_gate.value}", macro=macro)
        
        # === 阶段 2: 投资组合限制检查 ===
        positions = self.broker.get_positions()
        ctx.positions = positions
        if len([p for p in positions if p["quantity"] > 0]) >= ctx.max_positions:
            self.add_step(ctx, "portfolio_limit", "block", f"已达最大持仓数 {ctx.max_positions}")
            return ctx
        self.add_step(ctx, "portfolio_limit", "pass", f"当前持仓 {len(positions)}/{ctx.max_positions}")
        
        # === 阶段 3: 策略信号生成 ===
        configs = self.engine.normalize_configs(strategy_configs, symbols)
        result = self.engine.run(market_data, configs)
        self.add_step(ctx, "strategy_signals", "pass", f"生成 {len(result['signals'])} 个信号")
        
        # === 阶段 4: 制度匹配过滤 ===
        # 趋势突破策略只在 TREND 制度下启用
        # 均值回归策略只在 RANGE 制度下启用
        filtered_signals = []
        for signal in result["signals"]:
            closes = [c["close"] for c in market_data.get(signal["symbol"], [])]
            regime = self.regime_detector.detect(closes)
            strategy_type = signal.get("strategy_type", "")
            if strategy_type in ("dual_ma", "momentum") and regime["regime"] not in ("trend_up", "trend_down"):
                self.add_step(ctx, "regime_filter", "skip", f"{signal['strategy_id']} 制度不匹配: {regime['regime']}")
                continue
            if strategy_type in ("bollinger", "rsi") and regime["regime"] != "range":
                self.add_step(ctx, "regime_filter", "skip", f"{signal['strategy_id']} 制度不匹配: {regime['regime']}")
                continue
            filtered_signals.append(signal)
        self.add_step(ctx, "regime_filter", "pass", f"制度过滤后剩余 {len(filtered_signals)} 信号")
        
        # === 阶段 5: 宏观仓位乘数调整 ===
        multiplier = macro.get("position_multiplier", 0.5) if ctx.macro_gate == MacroGateLevel.ALLOW_REDUCED else 1.0
        for signal in filtered_signals:
            signal["position_multiplier"] = multiplier
        self.add_step(ctx, "macro_sizing", "pass", f"仓位乘数: {multiplier}")
        
        # === 阶段 6: 置信度门控 ===
        threshold = 0.35 if ctx.macro_gate == MacroGateLevel.ALLOW_REDUCED else 0.25
        confident_signals = [s for s in filtered_signals if s.get("confidence", 0) >= threshold]
        self.add_step(ctx, "confidence_gate", "pass", f"置信度阈值 {threshold}, 通过 {len(confident_signals)} 个")
        
        # === 阶段 7: 多周期冲突解决 ===
        # 同一 symbol 多个信号 → 按 confidence * weight 排序选最高
        resolved = self._resolve_conflicts(confident_signals)
        self.add_step(ctx, "conflict_resolution", "pass", f"冲突解决后 {len(resolved)} 信号")
        
        # === 阶段 8: 风险冷却检查 ===
        if self._in_cooldown():
            self.add_step(ctx, "cooldown_check", "block", "连续亏损冷却中")
            return ctx
        self.add_step(ctx, "cooldown_check", "pass", "无冷却")
        
        ctx.final_signals = resolved
        return ctx
    
    def _resolve_conflicts(self, signals: list[dict]) -> list[dict]:
        """同一 symbol 多信号 → 按分数排序选择最高分"""
        by_symbol: dict[str, list[dict]] = {}
        for s in signals:
            by_symbol.setdefault(s["symbol"], []).append(s)
        resolved = []
        for symbol, candidates in by_symbol.items():
            candidates.sort(key=lambda s: s.get("confidence", 0) * s.get("weight", 1), reverse=True)
            resolved.append(candidates[0])
        return resolved
    
    def _in_cooldown(self) -> bool:
        """检查是否处于连续亏损冷却期"""
        logs = self.broker.get_paper_logs(10)
        recent_losses = sum(1 for log in logs if log.get("event") == "order_filled" and log.get("realized_pnl", 0) < 0)
        return recent_losses >= 3  # 连续3次亏损 → 冷却
```

涉及的文件:
- 新建: `core/decision_pipeline.py` (~200行)
- 修改: `api/services/crypto_service.py` (集成管道 ~30行)

---

### 步骤 7：API — 制度检测端点

在 `api/routers/crypto.py` 增加:

```python
@router.get("/market/regime", summary="Detect market regime")
async def detect_market_regime(
    symbol: str = Query(..., description="Trading pair"),
    period: str = Query(default="1h"),
    limit: int = Query(default=100),
    service: CryptoService = Depends(get_crypto_service),
):
    klines = await service.get_klines(symbol, period, limit)
    closes = [k.close for k in klines.items]
    regime = service.regime_detector.detect(closes)
    return {"symbol": symbol, **regime}
```

---

## 第三阶段：影子交易与投资组合分析（优先级 🟡）

### 步骤 8：在 `CryptoPaperBrokerExecutor` 中增加影子交易模式

在现有 paper broker 基础上:

```python
# 在 CryptoPaperBrokerExecutor 类中新增

class ShadowPosition:
    """影子持仓 — 不与实际资金交互"""
    order_id: str
    symbol: str
    side: str
    theoretical_price: float
    executable_price: float  # 从订单簿估算
    slippage_bps: float
    quantity: float
    entry_time: str
    exit_time: str = ""
    realized_pnl: float = 0.0
    regime: str = ""
    strategy_id: str = ""

def place_shadow_order(self, symbol, action, quantity, theoretical_price, executable_price, strategy_id, regime):
    """下影子单 — 仅记录,不执行"""
    shadow = ShadowPosition(...)
    self._persist_shadow(shadow)
    return shadow

def get_shadow_positions(self) -> list[ShadowPosition]:
    """获取所有影子持仓"""
    pass

def sync_shadow_pnl(self, current_price: float):
    """按当前价格更新影子持仓浮动盈亏"""
    pass
```

涉及的 文件:
- 修改: `core/crypto_paper_broker.py` (~80行新增)
- SQLite 新增 `shadow_orders` 表

---

### 步骤 9：新建 `core/portfolio_returns.py` — 投资组合收益分析

```python
# core/portfolio_returns.py

def build_portfolio_returns(trades, shadow_orders, bills=None, timeframe="all"):
    """构建投资组合收益分析
    
    数据来源:
    1. local_trades → paper_broker 的交易记录
    2. shadow_orders → 影子订单
    3. exchange_bills → 交易所账单(未来接真实交易所时使用)
    
    返回:
    - equity_curve: [{timestamp, equity, drawdown}]
    - by_symbol: {symbol: {total_pnl, win_rate, profit_factor, trades[]}}
    - by_strategy: {strategy_id: {total_pnl, win_rate, profit_factor}}
    - summary: {total_pnl, total_return%, max_drawdown%, sharpe, calmar}
    """
    pass

def group_by_symbol(trades):
    """按交易对分组统计"""
    pass

def group_by_strategy(trades):
    """按策略分组统计"""
    pass

def calculate_drawdown_series(equity_curve):
    """计算回撤序列"""
    pass
```

涉及的文件:
- 新建: `core/portfolio_returns.py` (~200行)
- 修改: `api/routers/crypto.py` (新增 `/crypto/portfolio/returns` 端点)
- 修改: `api/models/response.py` (新增 PortfolioReturn 响应模型)

---

## 第四阶段：运维与质量保障（优先级 🟢）

### 步骤 10：Git 初始化

```bash
cd D:\auto_trader
git init
# 创建 .gitignore
```

`.gitignore` 内容:
```
__pycache__/
*.pyc
.venv/
node_modules/
dist/
release/
data/*.db
data/*.json
*.lock
.env
.secret.key
desktop/node_modules/
desktop/dist/
*.log
logs/
.AppData/
```

```bash
git add .
git commit -m "初始提交: 加密货币量化交易工作站"
```

---

### 步骤 11：凭证加密存储

```python
# 修改 core/credential_manager.py 增加加密功能

# 当前 credential_manager.py 已有基础加密框架
# 需要:
# 1. 取消 requirements.txt 中 cryptography 的注释
# 2. 在配置加载时自动检测明文密码并提示加密
# 3. config.yaml 中敏感字段改用加密值

# 在 config_loader.py 中增加:
def encrypt_sensitive_config(config: dict) -> dict:
    """加密配置中的敏感字段"""
    cm = CredentialManager()
    sensitive_keys = ["api_key", "api_secret", "password", "secret"]
    # 递归遍历,加密匹配的值
    pass
```

涉及的文件:
- 修改: `requirements.txt` (取消 cryptography 注释)
- 修改: `core/credential_manager.py` (增加批量加密方法)
- 修改: `config/config_loader.py` (集成加密)

---

### 步骤 12：邮件通知

```python
# 新建 core/notifier.py

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class TradeNotifier:
    """交易通知 — 邮件/企业微信"""
    
    def __init__(self, config: dict):
        self.smtp_config = config.get("smtp", {})
    
    def send_trade_alert(self, subject: str, body: str):
        """发送交易告警邮件"""
        msg = MIMEMultipart()
        msg["Subject"] = f"[AutoTrader] {subject}"
        msg["From"] = self.smtp_config.get("user")
        msg["To"] = self.smtp_config.get("recipient")
        msg.attach(MIMEText(body, "html"))
        # SMTP 发送
        pass
    
    def send_daily_summary(self, account_info: dict, trades: list):
        """发送每日交易汇总"""
        pass
```

涉及的文件:
- 新建: `core/notifier.py` (~80行)

---

### 步骤 13：前端增强 — K线图表

当前 `frontend/src/components/` 只有 `BacktestChart.vue` 和 `ConfirmDialog.vue`。

建议:
1. 安装 `lightweight-charts` (TradingView 开源图表库,适合 Vue):
   ```bash
   cd frontend
   npm install lightweight-charts
   ```

2. 新建 `frontend/src/components/CryptoKlineChart.vue`:
   - 接收 WebSocket 推送的实时 K 线数据
   - 支持切换时间周期 (1m/5m/15m/1h/4h/1d)
   - 叠加 MA/布林带指标线

3. 新建 `frontend/src/components/EquityCurveChart.vue`:
   - 权益曲线 + 回撤区域
   - 标注交易点

---

### 步骤 14：测试补充

新建测试文件:

```
tests/
├── test_crypto_only.py          # 已有 (6 tests)
├── test_walk_forward.py         # 新增: Walk-Forward 回测测试
├── test_regime_detector.py      # 新增: 制度检测测试
├── test_macro_risk.py           # 新增: 宏观风险门控测试
├── test_decision_pipeline.py    # 新增: 决策管道测试
└── test_portfolio_returns.py    # 新增: 投资组合分析测试
```

核心测试用例:

```python
# tests/test_regime_detector.py

def test_detect_trend_up():
    """上升趋势应检测为 TREND_UP"""
    # 构造连续上涨的价格序列
    closes = [100 + i * 0.5 for i in range(50)]
    detector = RegimeDetector()
    result = detector.detect(closes)
    assert result["regime"] == "trend_up"

def test_detect_range():
    """横盘应检测为 RANGE"""
    import random
    random.seed(42)
    closes = [100 + random.uniform(-1, 1) for _ in range(50)]
    detector = RegimeDetector()
    result = detector.detect(closes)
    assert result["regime"] == "range"
```

---

## 执行顺序总览

```
第1周 ─┬─ 步骤1: walk_forward_backtest.py (核心框架)
       ├─ 步骤2: backtest_with_grid (参数网格)
       └─ 步骤3: Walk-Forward API 端点

第2周 ─┬─ 步骤4: macro_risk.py (宏观门控)
       ├─ 步骤5: regime_detector.py (制度检测)
       └─ 步骤6: decision_pipeline.py (决策管道)

第3周 ─┬─ 步骤7: 制度检测 API
       ├─ 步骤8: 影子交易模式
       └─ 步骤9: portfolio_returns.py

第4周 ─┬─ 步骤10: Git 初始化
       ├─ 步骤11: 凭证加密
       ├─ 步骤12: 邮件通知
       ├─ 步骤13: K线图表前端
       └─ 步骤14: 测试补充
```

---

## 每个步骤的验证标准

| 步骤 | 验证方式 |
|------|----------|
| 1-3 | `pytest tests/test_walk_forward.py -v` 全部通过 |
| 4 | 手动调用 `/api/v1/crypto/macro/risk` 返回 DXY+M2 数据 |
| 5 | `pytest tests/test_regime_detector.py -v` 覆盖上升/下降/横盘 |
| 6 | `pytest tests/test_decision_pipeline.py -v` 模拟完整管道 |
| 7 | `GET /api/v1/crypto/market/regime?symbol=BTC/USDT` 返回制度 |
| 8 | 影子订单正确写入 SQLite,不改变账户余额 |
| 9 | `GET /api/v1/crypto/portfolio/returns` 返回分组统计 |
| 10 | `git log` 有提交记录 |
| 11 | config.yaml 中密码字段变为加密值 |
| 12 | 交易执行后收到邮件 |
| 13 | 前端显示实时K线图 |
| 14 | `pytest tests/ -v` 从 96 增加到 110+ |
