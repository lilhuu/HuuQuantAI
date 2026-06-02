"""Portfolio return analytics for paper and shadow trading.

The module merges local paper trades, open positions, and shadow positions into
one analytics shape: summary metrics, equity curve, group-by tables, and
normalized history rows. It intentionally does not contact a live exchange.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from statistics import fmean
from typing import Any, Callable, Literal


PortfolioReturnMode = Literal["live", "demo", "shadow"]
PortfolioReturnRange = Literal["7d", "30d", "90d", "all"]
PortfolioReturnSource = Literal["exchange_bill", "local_trade", "shadow"]
PortfolioReturnCacheStatus = Literal["fresh", "stale", "expired"]
PORTFOLIO_CACHE_FRESH_SECONDS = 20
PORTFOLIO_CACHE_STALE_SECONDS = 600
_PORTFOLIO_ANALYTICS_CACHE: dict[str, tuple[float, "PortfolioReturnAnalytics"]] = {}


@dataclass
class PortfolioReturnRow:
    id: str
    source: PortfolioReturnSource
    mode: PortfolioReturnMode
    symbol: str
    side: str
    strategy_id: str | None = None
    timeframe: str | None = None
    status: str = "open"
    opened_at: float | None = None
    closed_at: float | None = None
    timestamp: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    trade_roi_pct: float = 0.0
    account_return_pct: float = 0.0
    fee: float = 0.0
    slippage_bps: float | None = None
    margin: float | None = None
    notional: float | None = None
    amount: float | None = None
    amount_type: str | None = None
    leverage: float | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    mark_price: float | None = None
    tp_price: float | None = None
    sl_price: float | None = None
    regime: str | None = None
    macro_gate: str | None = None
    entry_reason: str | None = None
    exit_reason: str | None = None
    hold_minutes: float | None = None
    is_estimated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioReturnGroup:
    key: str
    trades: int
    closed_trades: int
    pnl: float
    realized_pnl: float
    unrealized_pnl: float
    win_rate: float
    profit_factor: float
    avg_trade_roi_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioReturnSummary:
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    account_return_pct: float
    avg_trade_roi_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    closed_trades: int
    open_trades: int
    total_rows: int
    gross_profit: float
    gross_loss: float
    fees: float
    avg_hold_minutes: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EquityCurvePoint:
    timestamp: float
    label: str
    cumulative_pnl: float
    equity: float
    account_return_pct: float
    drawdown_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioReturnAnalytics:
    mode: PortfolioReturnMode
    range: PortfolioReturnRange
    request_key: str
    generated_at: float
    capital_base: float
    capital_base_source: str
    summary: PortfolioReturnSummary
    source_status: PortfolioReturnCacheStatus = "fresh"
    _cache_time: float = 0.0
    _cache_ttl: float = float(PORTFOLIO_CACHE_FRESH_SECONDS)
    equity_curve: list[EquityCurvePoint] = field(default_factory=list)
    by_symbol: list[PortfolioReturnGroup] = field(default_factory=list)
    by_strategy: list[PortfolioReturnGroup] = field(default_factory=list)
    history: list[PortfolioReturnRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "range": self.range,
            "request_key": self.request_key,
            "generated_at": self.generated_at,
            "source_status": self.source_status,
            "_cache_time": self._cache_time,
            "_cache_ttl": self._cache_ttl,
            "capital_base": self.capital_base,
            "capital_base_source": self.capital_base_source,
            "summary": self.summary.to_dict(),
            "equity_curve": [item.to_dict() for item in self.equity_curve],
            "by_symbol": [item.to_dict() for item in self.by_symbol],
            "by_strategy": [item.to_dict() for item in self.by_strategy],
            "history": [item.to_dict() for item in self.history],
        }


def normalize_trade_row(row: dict[str, Any], capital_base: float, mode: PortfolioReturnMode = "demo") -> PortfolioReturnRow | None:
    """Convert a local paper trade or position dict into a normalized row."""
    status = str(row.get("status") or ("closed" if row.get("action") == "SELL" else "open")).lower()
    opened = _as_timestamp(row, "opened_at", "created_at", "timestamp")
    closed = _as_timestamp(row, "closed_at", "filled_time")
    timestamp = closed or opened or _now_ts()

    realized = _as_float(row, "realized_pnl") or 0.0
    unrealized = _as_float(row, "unrealized_pnl") or 0.0
    total_pnl = realized + unrealized
    if abs(total_pnl) < 1e-12 and status in {"settled", "closed"}:
        return None

    fee = _as_float(row, "fee") or 0.0
    entry = _as_float(row, "entry_price", "avg_price")
    exit_price = _as_float(row, "exit_price", "price")
    mark = _as_float(row, "mark_price", "current_price")
    margin = _as_float(row, "margin")
    notional = _as_float(row, "notional", "market_value")
    amount = _as_float(row, "amount", "quantity")
    leverage = _as_float(row, "leverage")
    trade_capital = _derive_trade_capital(margin, notional, amount, entry or exit_price, leverage)
    hold = _hold_minutes(opened, closed)
    side = str(row.get("side") or row.get("action") or "UNKNOWN").upper()

    return PortfolioReturnRow(
        id=str(row.get("id") or row.get("trade_id") or row.get("order_id") or f"{timestamp}_{row.get('symbol', 'trade')}"),
        source="local_trade",
        mode=mode,
        symbol=_norm_symbol(row.get("symbol", "")),
        side=side,
        strategy_id=str(row.get("strategy_id") or row.get("strategy") or "") or None,
        timeframe=str(row.get("timeframe") or "") or None,
        status=status,
        opened_at=opened,
        closed_at=closed,
        timestamp=timestamp,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        total_pnl=total_pnl,
        trade_roi_pct=_pct(total_pnl, trade_capital),
        account_return_pct=_pct(total_pnl, capital_base),
        fee=fee,
        slippage_bps=_as_float(row, "slippage_bps"),
        margin=margin,
        notional=notional,
        amount=amount,
        amount_type=str(row.get("amount_type") or "") or None,
        leverage=leverage,
        entry_price=entry,
        exit_price=exit_price if status in {"closed", "settled"} else None,
        mark_price=mark,
        tp_price=_as_float(row, "tp_price", "take_profit_price"),
        sl_price=_as_float(row, "sl_price", "stop_loss_price"),
        regime=str(row.get("regime") or "") or None,
        macro_gate=str(row.get("macro_gate") or "") or None,
        entry_reason=str(row.get("entry_reason") or row.get("reason") or "") or None,
        exit_reason=str(row.get("exit_reason") or row.get("reason") or "") or None,
        hold_minutes=hold,
        is_estimated=bool(row.get("is_estimated", False)),
    )


def normalize_shadow_row(row: dict[str, Any], capital_base: float) -> PortfolioReturnRow:
    """Convert a shadow position or shadow trade dict into a normalized row."""
    status = str(row.get("status") or ("closed" if str(row.get("action", "")).upper() == "SELL" else "open")).lower()
    opened = _as_timestamp(row, "opened_at", "created_at", "timestamp")
    closed = _as_timestamp(row, "closed_at")
    timestamp = closed or opened or _now_ts()
    entry = _as_float(row, "entry_price", "avg_price", "price")
    mark = _as_float(row, "mark_price", "current_price") or entry
    amount = _as_float(row, "amount", "quantity") or 0.0
    realized = _as_float(row, "realized_pnl") or 0.0
    unrealized = _as_float(row, "unrealized_pnl")
    if unrealized is None and status == "open" and entry and mark:
        unrealized = (mark - entry) * amount
    unrealized = unrealized or 0.0
    total_pnl = realized + unrealized
    notional = _as_float(row, "notional") or (amount * (entry or 0.0) if amount else None)

    return PortfolioReturnRow(
        id=str(row.get("id") or row.get("trade_id") or f"{timestamp}_{row.get('symbol', 'shadow')}"),
        source="shadow",
        mode="shadow",
        symbol=_norm_symbol(row.get("symbol", "")),
        side=str(row.get("side") or row.get("action") or "UNKNOWN").upper(),
        strategy_id=str(row.get("strategy_id") or row.get("signal_source") or "") or None,
        status=status,
        opened_at=opened,
        closed_at=closed,
        timestamp=timestamp,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        total_pnl=total_pnl,
        trade_roi_pct=_pct(total_pnl, notional),
        account_return_pct=_pct(total_pnl, capital_base),
        slippage_bps=_as_float(row, "slippage_bps"),
        notional=notional,
        amount=amount,
        entry_price=entry,
        exit_price=_as_float(row, "exit_price") if status == "closed" else None,
        mark_price=mark,
        tp_price=_as_float(row, "tp_price", "take_profit_price"),
        sl_price=_as_float(row, "sl_price", "stop_loss_price"),
        regime=str(row.get("regime") or "") or None,
        macro_gate=str(row.get("macro_gate") or "") or None,
        exit_reason=str(row.get("exit_reason") or "") or None,
        hold_minutes=_hold_minutes(opened, closed),
        is_estimated=True,
    )


def build_portfolio_return_analytics(
    mode: PortfolioReturnMode,
    range: PortfolioReturnRange = "30d",
    trades: list[dict[str, Any]] | None = None,
    shadow_orders: list[dict[str, Any]] | None = None,
    capital_base: float = 0.0,
    limit: int = 200,
    cache_ttl: int = PORTFOLIO_CACHE_FRESH_SECONDS,
    stale_ttl: int = PORTFOLIO_CACHE_STALE_SECONDS,
) -> PortfolioReturnAnalytics:
    """Build summary, curve, grouping, and history for portfolio returns."""
    safe_mode: PortfolioReturnMode = mode if mode in {"live", "demo", "shadow"} else "demo"  # type: ignore[assignment]
    safe_range: PortfolioReturnRange = range if range in {"7d", "30d", "90d", "all"} else "30d"  # type: ignore[assignment]
    safe_limit = max(1, min(int(limit or 200), 1000))
    now = _now_ts()
    safe_cache_ttl = max(1, int(cache_ttl or PORTFOLIO_CACHE_FRESH_SECONDS))
    safe_stale_ttl = max(safe_cache_ttl, int(stale_ttl or PORTFOLIO_CACHE_STALE_SECONDS))
    cache_key = _portfolio_cache_key(safe_mode, safe_range, trades or [], shadow_orders or [], capital_base, safe_limit)
    cached = _PORTFOLIO_ANALYTICS_CACHE.get(cache_key)
    if cached:
        cache_time, cached_analytics = cached
        age = now - cache_time
        if age <= safe_stale_ttl:
            result = copy.deepcopy(cached_analytics)
            result.source_status = "fresh" if age <= safe_cache_ttl else "stale"
            result.generated_at = now
            result._cache_time = cache_time
            result._cache_ttl = float(safe_cache_ttl)
            return result
    start_at = _range_start(safe_range, now)

    rows: list[PortfolioReturnRow] = []
    if safe_mode == "shadow":
        for item in shadow_orders or []:
            rows.append(normalize_shadow_row(item, capital_base))
    else:
        for item in trades or []:
            normalized = normalize_trade_row(item, capital_base, mode=safe_mode)
            if normalized:
                rows.append(normalized)

    rows = [row for row in rows if start_at <= 0 or row.timestamp >= start_at]
    rows.sort(key=lambda row: row.timestamp, reverse=True)

    requested_capital = float(capital_base or 0.0)
    if requested_capital <= 0:
        capital_base = _derive_fallback_capital(rows)
        capital_source = "fallback" if capital_base > 0 else "none"
    else:
        capital_base = requested_capital
        capital_source = "equity"

    for row in rows:
        row.account_return_pct = _pct(row.total_pnl, capital_base)

    history = rows[:safe_limit]
    closed = [row for row in history if _is_closed(row)]
    open_rows = [row for row in history if not _is_closed(row)]
    wins = [row for row in closed if row.total_pnl > 0]
    losses = [row for row in closed if row.total_pnl < 0]
    gross_profit = sum(row.total_pnl for row in wins)
    gross_loss = abs(sum(row.total_pnl for row in losses))
    roi_rows = [row for row in history if row.trade_roi_pct != 0]
    hold_rows = [row for row in closed if row.hold_minutes is not None]
    total_pnl = sum(row.total_pnl for row in history)
    realized_pnl = sum(row.realized_pnl for row in history)
    unrealized_pnl = sum(row.unrealized_pnl for row in history)
    equity_curve = _build_equity_curve(history, capital_base)

    summary = PortfolioReturnSummary(
        total_pnl=round(total_pnl, 8),
        realized_pnl=round(realized_pnl, 8),
        unrealized_pnl=round(unrealized_pnl, 8),
        account_return_pct=round(_pct(total_pnl, capital_base), 8),
        avg_trade_roi_pct=round(fmean([row.trade_roi_pct for row in roi_rows]), 8) if roi_rows else 0.0,
        win_rate=round((len(wins) / len(closed) * 100), 8) if closed else 0.0,
        profit_factor=round((gross_profit / gross_loss), 8) if gross_loss > 0 else (round(gross_profit, 8) if gross_profit > 0 else 0.0),
        max_drawdown_pct=round(min((point.drawdown_pct for point in equity_curve), default=0.0), 8),
        closed_trades=len(closed),
        open_trades=len(open_rows),
        total_rows=len(history),
        gross_profit=round(gross_profit, 8),
        gross_loss=round(gross_loss, 8),
        fees=round(sum(row.fee for row in history), 8),
        avg_hold_minutes=round(fmean([row.hold_minutes or 0.0 for row in hold_rows]), 8) if hold_rows else 0.0,
    )

    analytics = PortfolioReturnAnalytics(
        mode=safe_mode,
        range=safe_range,
        request_key=f"{safe_mode}:{safe_range}:{safe_limit}",
        generated_at=now,
        capital_base=round(float(capital_base or 0.0), 8),
        capital_base_source=capital_source,
        summary=summary,
        source_status="expired" if cached else "fresh",
        _cache_time=now,
        _cache_ttl=float(safe_cache_ttl),
        equity_curve=equity_curve,
        by_symbol=_group_rows(history, lambda row: row.symbol),
        by_strategy=_group_rows(history, lambda row: row.strategy_id or "unclassified"),
        history=history,
    )
    _PORTFOLIO_ANALYTICS_CACHE[cache_key] = (now, copy.deepcopy(analytics))
    if len(_PORTFOLIO_ANALYTICS_CACHE) > 128:
        oldest_key = min(_PORTFOLIO_ANALYTICS_CACHE, key=lambda key: _PORTFOLIO_ANALYTICS_CACHE[key][0])
        _PORTFOLIO_ANALYTICS_CACHE.pop(oldest_key, None)
    return analytics


def _portfolio_cache_key(
    mode: PortfolioReturnMode,
    range: PortfolioReturnRange,
    trades: list[dict[str, Any]],
    shadow_orders: list[dict[str, Any]],
    capital_base: float,
    limit: int,
) -> str:
    payload = {
        "mode": mode,
        "range": range,
        "trades": trades,
        "shadow_orders": shadow_orders,
        "capital_base": capital_base,
        "limit": limit,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            return number
    return None


def _as_timestamp(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        timestamp = _to_timestamp(value)
        if timestamp is not None:
            return timestamp
    return None


def _to_timestamp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number / 1000 if number > 10_000_000_000 else number
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
        return number / 1000 if number > 10_000_000_000 else number
    except ValueError:
        pass
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def _pct(numerator: float, denominator: float | None) -> float:
    if denominator is None or denominator <= 0:
        return 0.0
    return numerator / denominator * 100


def _range_start(range_value: PortfolioReturnRange, now: float) -> float:
    day = 86400
    if range_value == "7d":
        return now - 7 * day
    if range_value == "30d":
        return now - 30 * day
    if range_value == "90d":
        return now - 90 * day
    return 0.0


def _norm_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "/").replace("_", "/")


def _derive_trade_capital(
    margin: float | None,
    notional: float | None,
    amount: float | None,
    entry: float | None,
    leverage: float | None,
) -> float | None:
    if margin and margin > 0:
        return margin
    if notional and notional > 0:
        return notional / (leverage or 1.0)
    if amount and amount > 0 and entry and entry > 0:
        return amount * entry / (leverage or 1.0)
    return None


def _is_closed(row: PortfolioReturnRow) -> bool:
    if row.status in {"closed", "settled", "filled"} and row.side == "SELL":
        return True
    if row.status in {"closed", "settled"} and abs(row.realized_pnl) > 0:
        return True
    return bool(row.closed_at and row.realized_pnl != 0)


def _derive_fallback_capital(rows: list[PortfolioReturnRow]) -> float:
    candidates = []
    for row in rows:
        value = row.margin or row.notional or ((row.amount or 0.0) * (row.entry_price or row.mark_price or 0.0))
        if value and value > 0:
            candidates.append(value)
    return fmean(candidates) if candidates else 0.0


def _build_equity_curve(history: list[PortfolioReturnRow], capital_base: float) -> list[EquityCurvePoint]:
    cumulative = 0.0
    peak = 0.0
    points: list[EquityCurvePoint] = []
    for row in reversed(history):
        cumulative += row.total_pnl
        peak = max(peak, cumulative)
        drawdown_pct = _pct(min(0.0, cumulative - peak), capital_base)
        timestamp = row.timestamp or _now_ts()
        label = datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M")
        points.append(
            EquityCurvePoint(
                timestamp=timestamp,
                label=label,
                cumulative_pnl=round(cumulative, 8),
                equity=round((capital_base or 0.0) + cumulative, 8),
                account_return_pct=round(_pct(cumulative, capital_base), 8),
                drawdown_pct=round(drawdown_pct, 8),
            )
        )
    return points


def _profit_factor(rows: list[PortfolioReturnRow]) -> float:
    gross = sum(row.total_pnl for row in rows if row.total_pnl > 0)
    loss = abs(sum(row.total_pnl for row in rows if row.total_pnl < 0))
    if loss > 0:
        return gross / loss
    return gross if gross > 0 else 0.0


def _group_rows(rows: list[PortfolioReturnRow], key_fn: Callable[[PortfolioReturnRow], str]) -> list[PortfolioReturnGroup]:
    grouped: dict[str, list[PortfolioReturnRow]] = {}
    for row in rows:
        grouped.setdefault(key_fn(row) or "unclassified", []).append(row)

    result: list[PortfolioReturnGroup] = []
    for key, items in grouped.items():
        closed = [row for row in items if _is_closed(row)]
        wins = [row for row in closed if row.total_pnl > 0]
        roi_rows = [row for row in items if row.trade_roi_pct != 0]
        result.append(
            PortfolioReturnGroup(
                key=key,
                trades=len(items),
                closed_trades=len(closed),
                pnl=round(sum(row.total_pnl for row in items), 8),
                realized_pnl=round(sum(row.realized_pnl for row in items), 8),
                unrealized_pnl=round(sum(row.unrealized_pnl for row in items), 8),
                win_rate=round((len(wins) / len(closed) * 100), 8) if closed else 0.0,
                profit_factor=round(_profit_factor(items), 8),
                avg_trade_roi_pct=round(fmean([row.trade_roi_pct for row in roi_rows]), 8) if roi_rows else 0.0,
            )
        )
    result.sort(key=lambda group: abs(group.pnl), reverse=True)
    return result


def _hold_minutes(opened_at: float | None, closed_at: float | None) -> float | None:
    if opened_at is None or closed_at is None:
        return None
    return max((closed_at - opened_at) / 60, 0.0)


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()
