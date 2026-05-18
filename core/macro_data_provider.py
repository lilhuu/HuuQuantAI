"""Macro data provider for crypto risk gating.

All external data sources are optional. Missing packages, missing FRED keys,
or remote failures mark the affected factor unavailable instead of breaking the
local paper-trading system.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class MacroSnapshot:
    """One macro data snapshot."""

    timestamp: str = ""

    dxy_price: float = 0.0
    dxy_change_30d_pct: float = 0.0

    m2_latest: float = 0.0
    m2_change_3m_pct: float = 0.0

    btc_dominance: float = 0.0
    btc_dom_change_30d_pct: float = 0.0

    gold_price: float = 0.0
    gold_change_30d_pct: float = 0.0

    spx_price: float = 0.0
    spx_change_30d_pct: float = 0.0

    yield_10y: float = 0.0
    yield_2y: float = 0.0
    yield_spread_10y2y: float = 0.0

    dxy_available: bool = False
    m2_available: bool = False
    btc_dom_available: bool = False
    gold_available: bool = False
    spx_available: bool = False
    yields_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MacroDataProvider:
    """Fetch macro inputs from TradingView and FRED with soft failures."""

    CACHE_TTL_SHORT = 300
    CACHE_TTL_LONG = 3600

    def __init__(self, fred_api_key: str | None = None) -> None:
        self.fred_api_key = str(fred_api_key or "").strip()
        self._tv = None
        self._fred = None
        self._interval = None
        self._cache: dict[str, tuple[float, Any]] = {}

    def fetch_snapshot(self) -> MacroSnapshot:
        """Fetch a complete macro snapshot."""
        payload: dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat()}
        for key, func in (
            ("dxy", self._fetch_dxy),
            ("m2", self._fetch_m2),
            ("btc_dom", self._fetch_btc_dominance),
            ("gold", self._fetch_gold),
            ("spx", self._fetch_spx),
            ("yields", self._fetch_yields),
        ):
            payload.update(self._safe_fetch(func, key))
        return MacroSnapshot(**payload)

    @property
    def tv(self):
        if self._tv is None:
            from tvdatafeed import Interval, TvDatafeed  # type: ignore

            self._tv = TvDatafeed()
            self._interval = Interval
        return self._tv

    @property
    def interval(self):
        if self._interval is None:
            _ = self.tv
        return self._interval

    @property
    def fred(self):
        if self._fred is None and self.fred_api_key:
            from fredapi import Fred  # type: ignore

            self._fred = Fred(api_key=self.fred_api_key)
        return self._fred

    def _safe_fetch(self, func: Callable[[], dict[str, Any]], name: str) -> dict[str, Any]:
        try:
            return func()
        except Exception:
            return {f"{name}_available": False}

    def _fetch_dxy(self) -> dict[str, Any]:
        return self._cached(
            "dxy",
            self.CACHE_TTL_SHORT,
            lambda: self._fetch_tv_close_change(
                symbol="DXY",
                exchange="TVC",
                price_key="dxy_price",
                change_key="dxy_change_30d_pct",
                available_key="dxy_available",
            ),
        )

    def _fetch_btc_dominance(self) -> dict[str, Any]:
        return self._cached(
            "btc_dom",
            self.CACHE_TTL_SHORT,
            lambda: self._fetch_tv_close_change(
                symbol="BTC.D",
                exchange="CRYPTOCAP",
                price_key="btc_dominance",
                change_key="btc_dom_change_30d_pct",
                available_key="btc_dom_available",
            ),
        )

    def _fetch_gold(self) -> dict[str, Any]:
        return self._cached(
            "gold",
            self.CACHE_TTL_SHORT,
            lambda: self._fetch_tv_close_change(
                symbol="XAUUSD",
                exchange="TVC",
                price_key="gold_price",
                change_key="gold_change_30d_pct",
                available_key="gold_available",
            ),
        )

    def _fetch_spx(self) -> dict[str, Any]:
        return self._cached(
            "spx",
            self.CACHE_TTL_SHORT,
            lambda: self._fetch_tv_close_change(
                symbol="SPX",
                exchange="SP",
                price_key="spx_price",
                change_key="spx_change_30d_pct",
                available_key="spx_available",
            ),
        )

    def _fetch_m2(self) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            fred = self.fred
            if fred is None:
                return {"m2_available": False}
            series = fred.get_series("M2SL")
            values = self._dropna_values(series)
            if len(values) < 4:
                return {"m2_available": False}
            latest = float(values[-1])
            older = float(values[-4])
            change_3m = ((latest - older) / older * 100) if older else 0.0
            return {
                "m2_available": True,
                "m2_latest": round(latest, 2),
                "m2_change_3m_pct": round(change_3m, 4),
            }

        return self._cached("m2", self.CACHE_TTL_LONG, load)

    def _fetch_yields(self) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            fred = self.fred
            if fred is None:
                return {"yields_available": False}
            y10_values = self._dropna_values(fred.get_series("DGS10"))
            y2_values = self._dropna_values(fred.get_series("DGS2"))
            if not y10_values or not y2_values:
                return {"yields_available": False}
            latest_10y = float(y10_values[-1])
            latest_2y = float(y2_values[-1])
            return {
                "yields_available": True,
                "yield_10y": round(latest_10y, 4),
                "yield_2y": round(latest_2y, 4),
                "yield_spread_10y2y": round(latest_10y - latest_2y, 4),
            }

        return self._cached("yields", self.CACHE_TTL_LONG, load)

    def _fetch_tv_close_change(
        self,
        symbol: str,
        exchange: str,
        price_key: str,
        change_key: str,
        available_key: str,
    ) -> dict[str, Any]:
        frame = self.tv.get_hist(
            symbol=symbol,
            exchange=exchange,
            interval=self.interval.in_daily,
            n_bars=40,
        )
        closes = self._close_values(frame)
        if not closes:
            return {available_key: False}
        latest = float(closes[-1])
        reference = float(closes[-31]) if len(closes) >= 31 else float(closes[0])
        change = ((latest - reference) / reference * 100) if reference else 0.0
        return {
            available_key: True,
            price_key: round(latest, 2),
            change_key: round(change, 4),
        }

    def _cached(self, key: str, ttl_seconds: int, loader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < ttl_seconds:
            return dict(cached[1])
        value = loader()
        self._cache[key] = (now, dict(value))
        return value

    def _close_values(self, frame: Any) -> list[float]:
        try:
            if frame is None or frame.empty:
                return []
            return [float(value) for value in frame["close"].dropna().values]
        except Exception:
            return []

    def _dropna_values(self, series: Any) -> list[float]:
        try:
            return [float(value) for value in series.dropna().values]
        except Exception:
            return []
