#!/usr/bin/env python3
"""
Phase 8 回测运行脚本

流程:
    1. 使用 DataCollector 下载默认 15 只股票的历史行情
    2. 生成模拟情绪信号（基于简单均线/成交量启发式规则）
    3. 调用 BacktestEngine 执行回测
    4. 打印绩效摘要

用法:
    python -m backtest.run_backtest
    python -m backtest.run_backtest --start 2025-01-01 --end 2025-12-31
    python -m backtest.run_backtest --random   # 使用随机信号代替启发式
"""

import argparse
import logging
import sys
import os

import numpy as np
import pandas as pd

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backtest.data_collector import DataCollector
from backtest.engine import BacktestEngine

logger = logging.getLogger(__name__)

# ======================================================================
# 默认股票列表（与 scheduler.py 保持一致）
# ======================================================================
DEFAULT_STOCKS = [
    {"code": "600519", "name": "贵州茅台"},
    {"code": "000858", "name": "五粮液"},
    {"code": "300750", "name": "宁德时代"},
    {"code": "601318", "name": "中国平安"},
    {"code": "000333", "name": "美的集团"},
    {"code": "600036", "name": "招商银行"},
    {"code": "002594", "name": "比亚迪"},
    {"code": "601899", "name": "紫金矿业"},
    {"code": "600900", "name": "长江电力"},
    {"code": "000001", "name": "平安银行"},
    {"code": "002714", "name": "牧原股份"},
    {"code": "601012", "name": "隆基绿能"},
    {"code": "300059", "name": "东方财富"},
    {"code": "002475", "name": "立讯精密"},
    {"code": "600276", "name": "恒瑞医药"},
]

# 默认回测区间
DEFAULT_START = "2025-06-01"
DEFAULT_END = "2025-12-31"


# ======================================================================
# 信号生成
# ======================================================================

def generate_heuristic_signals(
    price_data: pd.DataFrame,
    stocks: list,
    short_window: int = 5,
    long_window: int = 20,
    volume_surge_ratio: float = 1.5,
) -> list:
    """
    基于简单启发式规则生成模拟买入信号。

    策略逻辑（替代真实情绪数据）:
        当满足以下 **任意两个** 条件时产生买入信号:
        1. 短期均线（5日）上穿长期均线（20日） — 趋势向上
        2. 当日成交量 > 前5日均量 * volume_surge_ratio — 放量
        3. 收盘价站上20日均线 — 多头排列

    信号评分 (0-100):
        - 均线交叉: +35
        - 放量: +30
        - 收盘高于均线: +25
        - 基础分: +10

    Args:
        price_data:         标准化行情 DataFrame
        stocks:             股票字典列表 [{"code": ..., "name": ...}]
        short_window:       短期均线窗口
        long_window:        长期均线窗口
        volume_surge_ratio: 放量倍数阈值

    Returns:
        信号列表，格式与 BacktestEngine.run() 要求一致
    """
    stock_map = {s["code"]: s["name"] for s in stocks}
    signals = []

    for code, group in price_data.groupby("stock_code"):
        df = group.sort_values("date").copy()
        if len(df) < long_window + 1:
            continue

        df["ma_short"] = df["close"].rolling(short_window).mean()
        df["ma_long"] = df["close"].rolling(long_window).mean()
        df["vol_ma5"] = df["volume"].rolling(5).mean()

        # 前一日均线值（用于判断交叉）
        df["prev_ma_short"] = df["ma_short"].shift(1)
        df["prev_ma_long"] = df["ma_long"].shift(1)

        for _, row in df.iterrows():
            if pd.isna(row["ma_long"]) or pd.isna(row["vol_ma5"]):
                continue

            score = 10  # 基础分
            conditions_met = 0

            # 条件 1: 均线金叉
            if (
                not pd.isna(row["prev_ma_short"])
                and not pd.isna(row["prev_ma_long"])
                and row["prev_ma_short"] <= row["prev_ma_long"]
                and row["ma_short"] > row["ma_long"]
            ):
                score += 35
                conditions_met += 1

            # 条件 2: 放量
            if row["vol_ma5"] > 0 and row["volume"] > row["vol_ma5"] * volume_surge_ratio:
                score += 30
                conditions_met += 1

            # 条件 3: 收盘站上长期均线
            if row["close"] > row["ma_long"]:
                score += 25
                conditions_met += 1

            # 至少满足两个条件才产生信号
            if conditions_met >= 2:
                sig_date = row["date"]
                if hasattr(sig_date, "strftime"):
                    sig_date = sig_date.strftime("%Y-%m-%d")

                signals.append({
                    "date": sig_date,
                    "stock_code": code,
                    "stock_name": stock_map.get(code, ""),
                    "score": score,
                    "signal": "BUY",
                })

    # 按日期升序、评分降序排列
    signals.sort(key=lambda s: (s["date"], -s["score"]))

    logger.info(
        "[SignalGen] 启发式信号: %d 条 (覆盖 %d 只股票)",
        len(signals),
        len(set(s["stock_code"] for s in signals)),
    )
    return signals


def generate_random_signals(
    price_data: pd.DataFrame,
    stocks: list,
    signal_prob: float = 0.03,
    seed: int = 42,
) -> list:
    """
    生成随机买入信号（作为基线对比）。

    每只股票每个交易日有 signal_prob 的概率产生买入信号，
    评分在 [40, 90] 之间均匀分布。

    Args:
        price_data:  标准化行情 DataFrame
        stocks:      股票字典列表
        signal_prob: 每日产生信号的概率
        seed:        随机种子（确保可复现）

    Returns:
        信号列表
    """
    rng = np.random.RandomState(seed)
    stock_map = {s["code"]: s["name"] for s in stocks}
    signals = []

    for code, group in price_data.groupby("stock_code"):
        dates = sorted(group["date"].unique())
        for d in dates:
            if rng.random() < signal_prob:
                sig_date = d
                if hasattr(sig_date, "strftime"):
                    sig_date = sig_date.strftime("%Y-%m-%d")

                signals.append({
                    "date": sig_date,
                    "stock_code": code,
                    "stock_name": stock_map.get(code, ""),
                    "score": int(rng.uniform(40, 90)),
                    "signal": "BUY",
                })

    signals.sort(key=lambda s: (s["date"], -s["score"]))

    logger.info(
        "[SignalGen] 随机信号: %d 条 (seed=%d)", len(signals), seed
    )
    return signals


# ======================================================================
# 主流程
# ======================================================================

def run(
    start_date: str = DEFAULT_START,
    end_date: str = DEFAULT_END,
    use_random: bool = False,
    stocks: list = None,
) -> dict:
    """
    执行完整回测流程。

    Args:
        start_date: 回测起始日期
        end_date:   回测截止日期
        use_random: True 使用随机信号，False 使用启发式信号
        stocks:     自定义股票列表，默认使用 DEFAULT_STOCKS

    Returns:
        BacktestEngine.run() 的结果字典
    """
    if stocks is None:
        stocks = DEFAULT_STOCKS

    stock_codes = [s["code"] for s in stocks]

    # ------------------------------------------------------------------
    # 1. 采集行情数据
    # ------------------------------------------------------------------
    print("=" * 60)
    print("  Phase 8 回测 — 数据采集")
    print("=" * 60)

    collector = DataCollector()

    # 为均线计算预留额外前置数据（30 个交易日约 45 个自然日）
    import datetime as _dt

    pre_start = (
        _dt.datetime.strptime(start_date.replace("-", ""), "%Y%m%d")
        - _dt.timedelta(days=45)
    ).strftime("%Y%m%d")

    print(f"  股票数量:   {len(stock_codes)}")
    print(f"  回测区间:   {start_date} ~ {end_date}")
    print(f"  数据区间:   {pre_start} ~ {end_date}（含均线预热期）")
    print()

    price_data = collector.collect_historical_data(stock_codes, pre_start, end_date)

    if price_data.empty:
        print("[ERROR] 未能获取任何行情数据，回测中止。")
        print("  可能原因: akshare 网络不通 / API 变更 / 股票代码有误")
        print("  建议: 部署到腾讯云后重试，或手动检查 akshare 版本")
        return {}

    print(f"  获取记录:   {len(price_data)} 条 ({price_data['stock_code'].nunique()} 只股票)")

    # 基准数据
    benchmark_data = collector.collect_benchmark_data(
        index_code="000300", start_date=start_date, end_date=end_date
    )
    if not benchmark_data.empty:
        print(f"  基准(CSI300): {len(benchmark_data)} 条")

    print()

    # ------------------------------------------------------------------
    # 2. 生成模拟信号
    # ------------------------------------------------------------------
    print("=" * 60)
    if use_random:
        print("  Phase 8 回测 — 随机信号生成")
    else:
        print("  Phase 8 回测 — 启发式信号生成")
    print("=" * 60)

    if use_random:
        signals = generate_random_signals(price_data, stocks)
    else:
        signals = generate_heuristic_signals(price_data, stocks)

    if not signals:
        print("[WARN] 未产生任何交易信号，回测中止。")
        print("  可能原因: 回测区间太短 / 行情数据不足")
        return {}

    # 仅保留回测区间内的信号统计
    in_range = [s for s in signals if start_date <= s["date"] <= end_date]
    print(f"  总信号数:       {len(signals)}")
    print(f"  区间内信号数:   {len(in_range)}")

    # 按股票统计
    from collections import Counter
    stock_counts = Counter(s["stock_code"] for s in in_range)
    print(f"  覆盖股票数:     {len(stock_counts)}")
    print(f"  平均评分:        {np.mean([s['score'] for s in in_range]):.1f}")
    print()

    # ------------------------------------------------------------------
    # 3. 运行回测引擎
    # ------------------------------------------------------------------
    print("=" * 60)
    print("  Phase 8 回测 — 引擎执行")
    print("=" * 60)

    engine = BacktestEngine()
    result = engine.run(
        signals=signals,
        price_data=price_data,
        start_date=start_date,
        end_date=end_date,
    )

    # ------------------------------------------------------------------
    # 4. 输出结果
    # ------------------------------------------------------------------
    print()
    engine.print_summary(result)

    # 补充基准收益信息
    if not benchmark_data.empty and len(benchmark_data) >= 2:
        bm = benchmark_data.sort_values("date")
        bm_start_close = bm.iloc[0]["close"]
        bm_end_close = bm.iloc[-1]["close"]
        if bm_start_close > 0:
            bm_return = (bm_end_close / bm_start_close - 1.0) * 100.0
            strategy_return = result.get("metrics", {}).get("total_return", 0)
            alpha = strategy_return - bm_return

            print()
            print("-" * 60)
            print(f"  CSI300 基准收益:  {bm_return:+.2f}%")
            print(f"  策略收益:         {strategy_return:+.2f}%")
            print(f"  超额收益 (alpha): {alpha:+.2f}%")
            print("-" * 60)

    return result


def main():
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="A股情绪选股系统 — Phase 8 全面回测"
    )
    parser.add_argument(
        "--start",
        default=DEFAULT_START,
        help=f"回测起始日期 (默认: {DEFAULT_START})",
    )
    parser.add_argument(
        "--end",
        default=DEFAULT_END,
        help=f"回测截止日期 (默认: {DEFAULT_END})",
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="使用随机信号（基线对比），否则使用启发式信号",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用详细日志",
    )

    args = parser.parse_args()

    # 配置日志
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    result = run(
        start_date=args.start,
        end_date=args.end,
        use_random=args.random,
    )

    if not result:
        sys.exit(1)

    # 返回退出码：有交易则 0，无交易则 1
    trades = result.get("trades", [])
    sys.exit(0 if trades else 1)


if __name__ == "__main__":
    main()
