# -*- coding: utf-8 -*-
"""
===================================
TickFlowFetcher - market review + K-line fallback
===================================

Current responsibilities:

1. Main A-share indices quotes
2. A-share market breadth statistics
3. Historical daily K-line fallback for CN/HK/US symbols

TickFlow still does not participate in the generic realtime quote pipeline.
Daily K-line usage is opt-in through DataFetcherManager fallback injection and
requires the API key from the Settings page (`TICKFLOW_API_KEY`).
"""

import logging
import math
import os
from threading import RLock
from time import monotonic
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .base import (
    BaseFetcher,
    DataFetchError,
    STANDARD_COLUMNS,
    _is_hk_market,
    _is_us_market,
    is_bse_code,
    is_kc_cy_stock,
    is_st_stock,
    normalize_stock_code,
)


logger = logging.getLogger(__name__)

_CN_MAIN_INDEX_QUOTES = (
    ("000001.SH", "000001", "上证指数"),
    ("399001.SZ", "399001", "深证成指"),
    ("399006.SZ", "399006", "创业板指"),
    ("000688.SH", "000688", "科创50"),
    ("000016.SH", "000016", "上证50"),
    ("000300.SH", "000300", "沪深300"),
)
_MAX_SYMBOLS_PER_QUOTE_REQUEST = 5
_UNIVERSE_PERMISSION_NEGATIVE_CACHE_TTL_SECONDS = 900
_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


class TickFlowFetcher(BaseFetcher):
    """TickFlow-backed market review helper."""

    name = "TickFlowFetcher"
    priority = 99

    def __init__(self, api_key: Optional[str], timeout: float = 30.0):
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self._client = None
        self._client_lock = RLock()
        self._universe_query_supported: Optional[bool] = None
        self._universe_query_checked_at: Optional[float] = None

    def close(self) -> None:
        """Close the underlying TickFlow client if it was created."""
        with self._client_lock:
            client = self._client
            self._client = None
            self._universe_query_supported = None
            self._universe_query_checked_at = None
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                logger.debug("[TickFlowFetcher] 关闭客户端失败: %s", exc)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Best-effort cleanup during interpreter shutdown.
            pass

    @staticmethod
    def _sanitize_proxy_env() -> None:
        """Normalize malformed proxy env values inherited from shell/UI settings."""
        for key in _PROXY_ENV_KEYS:
            value = os.environ.get(key)
            if value and "：" in value:
                os.environ[key] = value.replace("：", ":")
                logger.warning(
                    "[TickFlowFetcher] 代理环境变量 %s 包含全角冒号，已自动规范化",
                    key,
                )

    def _build_client(self):
        from tickflow import TickFlow

        self._sanitize_proxy_env()
        return TickFlow(api_key=self.api_key, timeout=self.timeout)

    def _get_client(self):
        if not self.api_key:
            return None
        if self._client is not None:
            return self._client

        with self._client_lock:
            if self._client is None:
                self._client = self._build_client()
            return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    def is_available_for_request(self, capability: str = "") -> bool:
        if not self.api_key:
            return False
        if not capability:
            return True
        return capability in {"daily_data", "market_review", "main_indices", "market_stats"}

    @staticmethod
    def _to_timestamp_ms(date_value: str, end_of_day: bool = False) -> int:
        base = datetime.strptime(date_value, "%Y-%m-%d")
        if end_of_day:
            base = base.replace(hour=23, minute=59, second=59, microsecond=999000)
        return int(base.timestamp() * 1000)

    @classmethod
    def _infer_market(cls, stock_code: str) -> str:
        normalized = normalize_stock_code(stock_code)
        if _is_us_market(normalized):
            return "us"
        if _is_hk_market(normalized):
            return "hk"
        if is_bse_code(normalized):
            return "bj"
        if normalized.startswith(("5", "6", "9")):
            return "sh"
        return "sz"

    @classmethod
    def _to_tickflow_symbol(cls, stock_code: str) -> str:
        normalized = normalize_stock_code(stock_code).strip().upper()
        market = cls._infer_market(normalized)
        if market == "hk":
            if normalized.startswith("HK"):
                normalized = normalized[2:]
            return f"{normalized.zfill(5)}.HK"
        if market == "us":
            return normalized if normalized.endswith(".US") else f"{normalized}.US"
        if market == "bj":
            return f"{normalized}.BJ"
        if market == "sh":
            return f"{normalized}.SH"
        return f"{normalized}.SZ"

    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        client = self._get_client()
        if client is None:
            raise DataFetchError("TickFlow API key is not configured")

        symbol = self._to_tickflow_symbol(stock_code)
        start_time = self._to_timestamp_ms(start_date, end_of_day=False)
        end_time = self._to_timestamp_ms(end_date, end_of_day=True)

        try:
            frame = client.klines.get(
                symbol,
                period="1d",
                start_time=start_time,
                end_time=end_time,
                adjust="forward",
                as_dataframe=True,
            )
        except Exception as exc:
            raise DataFetchError(f"TickFlow 获取 {symbol} 日线失败: {exc}") from exc

        if frame is None:
            raise DataFetchError(f"TickFlow 返回空结果: {symbol}")

        if isinstance(frame, pd.DataFrame):
            return frame.copy()

        if isinstance(frame, dict):
            compact = pd.DataFrame(frame)
            if not compact.empty and "timestamp" in compact.columns:
                compact["trade_date"] = pd.to_datetime(
                    compact["timestamp"], unit="ms", errors="coerce"
                ).dt.strftime("%Y-%m-%d")
            return compact

        if hasattr(frame, "to_dict"):
            return pd.DataFrame(frame.to_dict("records"))

        raise DataFetchError(f"TickFlow 返回了不支持的 K 线格式: {type(frame).__name__}")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df is None or df.empty:
            raise DataFetchError(f"TickFlow 未获取到 {stock_code} 的日线数据")

        normalized = df.copy()

        if "trade_date" in normalized.columns:
            date_series = pd.to_datetime(normalized["trade_date"], errors="coerce")
        elif "date" in normalized.columns:
            date_series = pd.to_datetime(normalized["date"], errors="coerce")
        elif "trade_time" in normalized.columns:
            date_series = pd.to_datetime(normalized["trade_time"], errors="coerce")
        elif "timestamp" in normalized.columns:
            date_series = pd.to_datetime(normalized["timestamp"], unit="ms", errors="coerce")
        elif isinstance(normalized.index, pd.DatetimeIndex):
            date_series = pd.to_datetime(normalized.index, errors="coerce")
        else:
            raise DataFetchError("TickFlow K线数据缺少日期字段")

        result = pd.DataFrame(
            {
                "date": date_series,
                "open": pd.to_numeric(normalized.get("open"), errors="coerce"),
                "high": pd.to_numeric(normalized.get("high"), errors="coerce"),
                "low": pd.to_numeric(normalized.get("low"), errors="coerce"),
                "close": pd.to_numeric(normalized.get("close"), errors="coerce"),
                "volume": pd.to_numeric(
                    normalized.get("volume", normalized.get("vol")),
                    errors="coerce",
                ),
                "amount": pd.to_numeric(
                    normalized.get("amount", normalized.get("turnover", 0.0)),
                    errors="coerce",
                ),
            }
        )

        prev_close_raw = normalized.get("prev_close")
        prev_close = (
            pd.to_numeric(prev_close_raw, errors="coerce")
            if prev_close_raw is not None
            else None
        )
        if isinstance(prev_close, pd.Series) and not prev_close.isna().all():
            result["pct_chg"] = ((result["close"] - prev_close) / prev_close) * 100
        else:
            result["pct_chg"] = result["close"].pct_change().fillna(0.0) * 100

        result["pct_chg"] = result["pct_chg"].fillna(0.0)
        result["amount"] = result["amount"].fillna(0.0)

        missing = [col for col in STANDARD_COLUMNS if col not in result.columns]
        if missing:
            raise DataFetchError(f"TickFlow 标准化缺少列: {', '.join(missing)}")

        return result[STANDARD_COLUMNS]

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _ratio_to_percent(cls, value: Any) -> Optional[float]:
        ratio = cls._safe_float(value)
        if ratio is None:
            return None
        return ratio * 100.0

    @staticmethod
    def _extract_name(quote: Dict[str, Any]) -> str:
        ext = quote.get("ext") or {}
        name = ext.get("name") or quote.get("name") or ""
        return str(name).strip()

    @staticmethod
    def _is_universe_permission_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        code = str(getattr(exc, "code", "") or "").upper()
        message = (
            f"{getattr(exc, 'message', '')} {exc}"
        ).strip().lower()

        if status_code == 403:
            return True
        if code in {"PERMISSION_DENIED", "FORBIDDEN"}:
            return True
        return any(
            keyword in message
            for keyword in (
                "标的池查询",
                "universe",
                "permission",
                "forbidden",
            )
        )

    @staticmethod
    def _is_cn_equity_symbol(symbol: str) -> bool:
        normalized = normalize_stock_code(symbol)
        upper_symbol = (symbol or "").strip().upper()
        return (
            normalized.isdigit()
            and len(normalized) == 6
            and upper_symbol.endswith((".SH", ".SZ", ".BJ"))
        )

    @staticmethod
    def _round_limit_price(prev_close: float, ratio: float) -> float:
        return math.floor(prev_close * (1 + ratio) * 100 + 0.5) / 100.0

    @classmethod
    def _get_limit_ratio(cls, pure_code: str, name: str) -> float:
        if is_bse_code(pure_code):
            return 0.30
        if is_kc_cy_stock(pure_code):
            return 0.20
        if is_st_stock(name):
            return 0.05
        return 0.10

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        """Fetch main A-share indices via TickFlow quotes."""
        if region != "cn":
            return None

        client = self._get_client()
        if client is None:
            return None

        symbols = [symbol for symbol, _, _ in _CN_MAIN_INDEX_QUOTES]
        quotes: List[Dict[str, Any]] = []
        for offset in range(0, len(symbols), _MAX_SYMBOLS_PER_QUOTE_REQUEST):
            batch_symbols = symbols[offset : offset + _MAX_SYMBOLS_PER_QUOTE_REQUEST]
            batch_quotes = client.quotes.get(symbols=batch_symbols)
            if batch_quotes:
                quotes.extend(batch_quotes)
        if not quotes:
            logger.warning("[TickFlowFetcher] 指数行情为空")
            return None

        quotes_by_symbol = {
            str(item.get("symbol", "")).upper(): item for item in quotes if item
        }
        results: List[Dict[str, Any]] = []

        for symbol, code, name in _CN_MAIN_INDEX_QUOTES:
            quote = quotes_by_symbol.get(symbol)
            if not quote:
                continue

            ext = quote.get("ext") or {}
            current = self._safe_float(quote.get("last_price")) or 0.0
            prev_close = self._safe_float(quote.get("prev_close")) or 0.0
            change = self._safe_float(ext.get("change_amount"))
            if change is None:
                change = current - prev_close if current or prev_close else 0.0
            amplitude = self._ratio_to_percent(ext.get("amplitude"))
            if amplitude is None and prev_close > 0:
                high = self._safe_float(quote.get("high")) or 0.0
                low = self._safe_float(quote.get("low")) or 0.0
                amplitude = (high - low) / prev_close * 100

            results.append(
                {
                    "code": code,
                    "name": name,
                    "current": current,
                    "change": change,
                    "change_pct": self._ratio_to_percent(ext.get("change_pct")) or 0.0,
                    "open": self._safe_float(quote.get("open")) or 0.0,
                    "high": self._safe_float(quote.get("high")) or 0.0,
                    "low": self._safe_float(quote.get("low")) or 0.0,
                    "prev_close": prev_close,
                    "volume": self._safe_float(quote.get("volume")) or 0.0,
                    "amount": self._safe_float(quote.get("amount")) or 0.0,
                    "amplitude": amplitude or 0.0,
                }
            )

        if len(results) != len(_CN_MAIN_INDEX_QUOTES):
            logger.warning(
                "[TickFlowFetcher] 指数行情不完整: %s/%s",
                len(results),
                len(_CN_MAIN_INDEX_QUOTES),
            )
            return None

        return results or None

    def get_market_stats(self) -> Optional[Dict[str, Any]]:
        """Calculate A-share market breadth from TickFlow universe quotes."""
        client = self._get_client()
        if client is None:
            return None

        now = monotonic()
        if self._universe_query_supported is False:
            checked_at = self._universe_query_checked_at or 0.0
            if (
                now - checked_at
                < _UNIVERSE_PERMISSION_NEGATIVE_CACHE_TTL_SECONDS
            ):
                return None
            self._universe_query_supported = None
            self._universe_query_checked_at = None

        try:
            quotes = client.quotes.get(universes=["CN_Equity_A"])
            self._universe_query_supported = True
            self._universe_query_checked_at = now
        except Exception as exc:
            if self._is_universe_permission_error(exc):
                self._universe_query_supported = False
                self._universe_query_checked_at = now
                logger.info(
                    "[TickFlowFetcher] 当前套餐不支持标的池查询，市场统计回退到现有数据源"
                )
                return None
            raise
        if not quotes:
            logger.warning("[TickFlowFetcher] 市场统计行情为空")
            return None

        stats = {
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "total_amount": 0.0,
        }
        valid_rows = 0

        for quote in quotes:
            if not quote:
                continue

            symbol = str(quote.get("symbol") or "").strip().upper()
            if not self._is_cn_equity_symbol(symbol):
                continue

            amount = self._safe_float(quote.get("amount"))
            if amount is not None and amount > 0:
                stats["total_amount"] += amount / 1e8

            pure_code = normalize_stock_code(symbol)
            last_price = self._safe_float(quote.get("last_price"))
            prev_close = self._safe_float(quote.get("prev_close"))

            if last_price is None or prev_close is None or amount is None or amount <= 0:
                continue

            name = self._extract_name(quote)
            if not name:
                logger.debug("[TickFlowFetcher] 缺少股票名称，按非 ST 处理: %s", symbol)

            ratio = self._get_limit_ratio(pure_code, name)
            limit_up = self._round_limit_price(prev_close, ratio)
            limit_down = math.floor(prev_close * (1 - ratio) * 100 + 0.5) / 100.0
            limit_up_tolerance = round(abs(prev_close * (1 + ratio) - limit_up), 10)
            limit_down_tolerance = round(
                abs(prev_close * (1 - ratio) - limit_down), 10
            )

            valid_rows += 1

            if abs(last_price - limit_up) <= limit_up_tolerance:
                stats["limit_up_count"] += 1
            if abs(last_price - limit_down) <= limit_down_tolerance:
                stats["limit_down_count"] += 1

            if last_price > prev_close:
                stats["up_count"] += 1
            elif last_price < prev_close:
                stats["down_count"] += 1
            else:
                stats["flat_count"] += 1

        if valid_rows == 0:
            logger.warning("[TickFlowFetcher] 市场统计未命中有效 A 股行情")
            return None

        return stats
