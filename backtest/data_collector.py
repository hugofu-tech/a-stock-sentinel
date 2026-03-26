"""
回测数据采集模块

使用 akshare 下载 A 股历史日线行情和指数基准数据，
支持本地文件缓存以避免重复请求。
"""

import hashlib
import logging
import os
import time
from datetime import datetime
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 缓存目录（项目根目录下 data/cache）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, "data", "cache")

# akshare 请求间隔（秒），避免触发频率限制
_REQUEST_INTERVAL = 0.5


class DataCollector:
    """
    A 股历史行情数据采集器。

    功能:
        - 通过 akshare 下载个股日线 OHLCV（前复权）
        - 通过 akshare 下载指数日线数据（沪深 300 等）
        - 本地 parquet 文件缓存，按 (股票代码, 起止日期) 生成唯一键
        - 自动创建缓存目录
        - API 错误优雅降级（跳过失败股票，记录日志）
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Args:
            cache_dir: 自定义缓存目录。默认为 data/cache/
        """
        self.cache_dir = cache_dir or _CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    # ==================================================================
    # 公开接口
    # ==================================================================

    def collect_historical_data(
        self,
        stock_codes: List[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        批量下载个股历史日线行情。

        Args:
            stock_codes: 股票代码列表，如 ['600519', '000858']
            start_date:  起始日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'
            end_date:    截止日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'

        Returns:
            DataFrame，列: date, stock_code, open, high, low, close, volume
            如果全部失败则返回空 DataFrame（保持相同列结构）。
        """
        start_fmt = self._normalize_date(start_date)
        end_fmt = self._normalize_date(end_date)

        frames: List[pd.DataFrame] = []
        total = len(stock_codes)

        for idx, code in enumerate(stock_codes, 1):
            logger.info(
                "[DataCollector] 下载个股行情 %s (%d/%d)", code, idx, total
            )
            df = self._fetch_stock(code, start_fmt, end_fmt)
            if df is not None and not df.empty:
                frames.append(df)

        if not frames:
            logger.warning("[DataCollector] 未获取到任何个股行情数据")
            return pd.DataFrame(
                columns=["date", "stock_code", "open", "high", "low", "close", "volume"]
            )

        result = pd.concat(frames, ignore_index=True)
        result = result.sort_values(["stock_code", "date"]).reset_index(drop=True)

        logger.info(
            "[DataCollector] 共获取 %d 只股票、%d 条行情记录",
            result["stock_code"].nunique(),
            len(result),
        )
        return result

    def collect_benchmark_data(
        self,
        index_code: str = "000300",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """
        下载指数历史日线行情（用于基准对比）。

        Args:
            index_code: 指数代码，默认 '000300'（沪深 300）
            start_date: 起始日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'
            end_date:   截止日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'

        Returns:
            DataFrame，列: date, stock_code, open, high, low, close, volume
        """
        start_fmt = self._normalize_date(start_date) if start_date else ""
        end_fmt = self._normalize_date(end_date) if end_date else ""

        # 检查缓存
        cache_key = self._make_cache_key(f"idx_{index_code}", start_fmt, end_fmt)
        cached = self._read_cache(cache_key)
        if cached is not None:
            logger.info("[DataCollector] 命中基准缓存: %s", index_code)
            return cached

        # akshare 指数接口使用 "shXXXXXX" / "szXXXXXX" 格式
        symbol = self._index_symbol(index_code)

        try:
            import akshare as ak

            logger.info("[DataCollector] 通过 akshare 下载指数 %s", symbol)
            raw = ak.stock_zh_index_daily(symbol=symbol)
        except Exception as exc:
            logger.error(
                "[DataCollector] 下载指数 %s 失败: %s", index_code, exc
            )
            return pd.DataFrame(
                columns=["date", "stock_code", "open", "high", "low", "close", "volume"]
            )

        if raw is None or raw.empty:
            logger.warning("[DataCollector] 指数 %s 返回空数据", index_code)
            return pd.DataFrame(
                columns=["date", "stock_code", "open", "high", "low", "close", "volume"]
            )

        df = self._standardize_index_df(raw, index_code)

        # 按日期过滤
        if start_fmt:
            start_dt = pd.Timestamp(start_fmt)
            df = df[df["date"] >= start_dt]
        if end_fmt:
            end_dt = pd.Timestamp(end_fmt)
            df = df[df["date"] <= end_dt]

        df = df.reset_index(drop=True)
        self._write_cache(cache_key, df)

        logger.info(
            "[DataCollector] 基准 %s: %d 条记录", index_code, len(df)
        )
        return df

    # ==================================================================
    # 内部方法 — 个股
    # ==================================================================

    def _fetch_stock(
        self, code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """
        下载单只股票的日线行情，优先读取缓存。

        Returns:
            标准化后的 DataFrame，失败时返回 None。
        """
        cache_key = self._make_cache_key(code, start_date, end_date)
        cached = self._read_cache(cache_key)
        if cached is not None:
            logger.debug("[DataCollector] 命中缓存: %s", code)
            return cached

        try:
            import akshare as ak

            time.sleep(_REQUEST_INTERVAL)

            raw = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        except Exception as exc:
            logger.error("[DataCollector] 下载 %s 失败: %s", code, exc)
            return None

        if raw is None or raw.empty:
            logger.warning("[DataCollector] %s 返回空数据", code)
            return None

        df = self._standardize_stock_df(raw, code)
        self._write_cache(cache_key, df)
        return df

    # ==================================================================
    # 数据标准化
    # ==================================================================

    @staticmethod
    def _standardize_stock_df(raw: pd.DataFrame, code: str) -> pd.DataFrame:
        """
        将 akshare stock_zh_a_hist 返回的 DataFrame 标准化为统一格式。

        akshare 返回列通常为:
            日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
        """
        df = raw.copy()

        # 映射列名（兼容中英文）
        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        df = df.rename(columns=col_map)

        # 如果 akshare 版本返回英文列名
        eng_map = {
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        df = df.rename(columns=eng_map)

        required = {"date", "open", "high", "low", "close", "volume"}
        if not required.issubset(set(df.columns)):
            # 按位置兜底（akshare 偶尔改列名）
            if len(df.columns) >= 6:
                df = df.iloc[:, :6]
                df.columns = ["date", "open", "close", "high", "low", "volume"]
            else:
                logger.warning("股票 %s 列不足，无法标准化", code)
                return pd.DataFrame(
                    columns=["date", "stock_code", "open", "high", "low", "close", "volume"]
                )

        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        df["stock_code"] = code
        df["date"] = pd.to_datetime(df["date"])

        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["date", "open", "close"])
        df = df[["date", "stock_code", "open", "high", "low", "close", "volume"]]
        return df.reset_index(drop=True)

    @staticmethod
    def _standardize_index_df(raw: pd.DataFrame, index_code: str) -> pd.DataFrame:
        """
        将 akshare stock_zh_index_daily 返回的 DataFrame 标准化。

        典型列: date, open, high, low, close, volume
        """
        df = raw.copy()

        # 映射中文列名（如有）
        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        df = df.rename(columns=col_map)

        # 英文列名标准化（小写）
        df.columns = [c.lower().strip() for c in df.columns]

        df["stock_code"] = index_code
        df["date"] = pd.to_datetime(df["date"])

        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = 0.0

        df = df[["date", "stock_code", "open", "high", "low", "close", "volume"]]
        return df.reset_index(drop=True)

    # ==================================================================
    # 缓存
    # ==================================================================

    def _make_cache_key(self, code: str, start: str, end: str) -> str:
        """生成缓存文件名（基于参数哈希）。"""
        raw_key = f"{code}_{start}_{end}"
        digest = hashlib.md5(raw_key.encode()).hexdigest()[:12]
        return f"{code}_{digest}.parquet"

    def _read_cache(self, cache_key: str) -> Optional[pd.DataFrame]:
        """从本地缓存读取 DataFrame。"""
        path = os.path.join(self.cache_dir, cache_key)
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_parquet(path)
            logger.debug("[Cache] 读取: %s", path)
            return df
        except Exception as exc:
            logger.warning("[Cache] 读取失败 %s: %s", path, exc)
            return None

    def _write_cache(self, cache_key: str, df: pd.DataFrame) -> None:
        """将 DataFrame 写入本地缓存。"""
        path = os.path.join(self.cache_dir, cache_key)
        try:
            df.to_parquet(path, index=False)
            logger.debug("[Cache] 写入: %s", path)
        except Exception as exc:
            logger.warning("[Cache] 写入失败 %s: %s", path, exc)

    def clear_cache(self) -> int:
        """清除所有缓存文件，返回删除的文件数。"""
        count = 0
        if not os.path.isdir(self.cache_dir):
            return count
        for fname in os.listdir(self.cache_dir):
            if fname.endswith(".parquet"):
                try:
                    os.remove(os.path.join(self.cache_dir, fname))
                    count += 1
                except OSError:
                    pass
        logger.info("[Cache] 清除 %d 个缓存文件", count)
        return count

    # ==================================================================
    # 工具
    # ==================================================================

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """
        将日期字符串统一为 'YYYYMMDD' 格式（akshare 要求）。

        支持输入: 'YYYY-MM-DD', 'YYYYMMDD', 'YYYY/MM/DD'
        """
        cleaned = date_str.replace("-", "").replace("/", "")
        # 验证格式
        try:
            datetime.strptime(cleaned, "%Y%m%d")
        except ValueError:
            raise ValueError(f"无法解析日期: {date_str!r}，请使用 YYYYMMDD 或 YYYY-MM-DD 格式")
        return cleaned

    @staticmethod
    def _index_symbol(index_code: str) -> str:
        """
        将指数代码转换为 akshare stock_zh_index_daily 所需的带交易所前缀格式。

        规则:
            - 000xxx, 399xxx -> 'szXXXXXX' (深交所)
            - 其他 -> 'shXXXXXX' (上交所)
        """
        code = index_code.strip()
        if code.startswith("39") or code.startswith("00"):
            return f"sz{code}"
        return f"sh{code}"
