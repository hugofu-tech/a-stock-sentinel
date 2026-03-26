"""
回测绩效指标计算模块

计算交易策略的各项绩效指标，包括收益率、夏普比率、最大回撤等。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 年化交易日数
TRADING_DAYS_PER_YEAR = 252
# 无风险利率（年化）
RISK_FREE_RATE = 0.025


def calculate_metrics(
    trades: List[Dict],
    initial_capital: float = 100000,
    benchmark_returns: Optional[pd.Series] = None,
) -> Dict:
    """
    根据交易记录计算完整绩效指标。

    Args:
        trades: 交易列表，每笔交易为 dict，包含以下字段：
            - entry_date: 买入日期 (str 或 datetime)
            - exit_date:  卖出日期 (str 或 datetime)
            - entry_price: 买入价格
            - exit_price:  卖出价格
            - stock_code:  股票代码
            - return_pct:  单笔收益率 (%)
        initial_capital: 初始资金（元）
        benchmark_returns: 基准日收益率序列（可选），index 为日期

    Returns:
        包含各项绩效指标的字典
    """
    result = {
        'total_return': 0.0,
        'annualized_return': 0.0,
        'sharpe_ratio': 0.0,
        'max_drawdown': 0.0,
        'win_rate': 0.0,
        'profit_factor': 0.0,
        'total_trades': 0,
        'avg_return': 0.0,
        'avg_hold_days': 0.0,
        'best_trade': 0.0,
        'worst_trade': 0.0,
        'benchmark_return': None,
    }

    if not trades:
        logger.warning("交易列表为空，返回零值指标")
        return result

    # ------------------------------------------------------------------
    # 基础统计
    # ------------------------------------------------------------------
    returns = []
    hold_days_list = []

    for t in trades:
        try:
            ret = float(t.get('return_pct', 0.0))
            returns.append(ret)

            entry_dt = _parse_date(t['entry_date'])
            exit_dt = _parse_date(t['exit_date'])
            hold_days = (exit_dt - entry_dt).days
            hold_days_list.append(max(hold_days, 1))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("跳过无效交易记录: %s, 原因: %s", t, exc)
            continue

    if not returns:
        logger.warning("没有有效的交易收益数据")
        return result

    returns_arr = np.array(returns, dtype=np.float64)
    total_trades = len(returns_arr)

    # ------------------------------------------------------------------
    # 胜率 / 盈亏比
    # ------------------------------------------------------------------
    wins = returns_arr[returns_arr > 0]
    losses = returns_arr[returns_arr < 0]
    win_rate = len(wins) / total_trades * 100.0

    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = float(np.abs(np.sum(losses))) if len(losses) > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

    # ------------------------------------------------------------------
    # 累计收益 / 年化收益
    # ------------------------------------------------------------------
    equity_curve = _build_equity_from_returns(returns_arr, initial_capital)
    final_equity = equity_curve[-1]
    total_return = (final_equity / initial_capital - 1.0) * 100.0

    # 交易跨度（自然日）
    all_dates = []
    for t in trades:
        try:
            all_dates.append(_parse_date(t['entry_date']))
            all_dates.append(_parse_date(t['exit_date']))
        except (KeyError, TypeError, ValueError):
            continue

    if len(all_dates) >= 2:
        span_days = (max(all_dates) - min(all_dates)).days
    else:
        span_days = sum(hold_days_list)

    span_years = max(span_days / 365.25, 1.0 / 365.25)
    annualized_return = ((final_equity / initial_capital) ** (1.0 / span_years) - 1.0) * 100.0

    # ------------------------------------------------------------------
    # 夏普比率（基于单笔交易收益率序列换算日频）
    # ------------------------------------------------------------------
    sharpe_ratio = _calculate_sharpe(returns_arr, hold_days_list)

    # ------------------------------------------------------------------
    # 最大回撤
    # ------------------------------------------------------------------
    max_drawdown = _calculate_max_drawdown(equity_curve)

    # ------------------------------------------------------------------
    # 基准收益
    # ------------------------------------------------------------------
    benchmark_return = None
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        try:
            benchmark_return = float((1.0 + benchmark_returns).prod() - 1.0) * 100.0
        except Exception as exc:
            logger.warning("基准收益计算失败: %s", exc)

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------
    result.update({
        'total_return': round(total_return, 4),
        'annualized_return': round(annualized_return, 4),
        'sharpe_ratio': round(sharpe_ratio, 4),
        'max_drawdown': round(max_drawdown, 4),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 4) if np.isfinite(profit_factor) else float('inf'),
        'total_trades': total_trades,
        'avg_return': round(float(np.mean(returns_arr)), 4),
        'avg_hold_days': round(float(np.mean(hold_days_list)), 2),
        'best_trade': round(float(np.max(returns_arr)), 4),
        'worst_trade': round(float(np.min(returns_arr)), 4),
        'benchmark_return': round(benchmark_return, 4) if benchmark_return is not None else None,
    })

    return result


def calculate_daily_equity(
    trades: List[Dict],
    initial_capital: float = 100000,
) -> pd.DataFrame:
    """
    根据交易记录生成按日权益曲线。

    Args:
        trades: 交易列表（同 calculate_metrics）
        initial_capital: 初始资金

    Returns:
        DataFrame，列: date, equity, drawdown
    """
    if not trades:
        logger.warning("交易列表为空，返回空 DataFrame")
        return pd.DataFrame(columns=['date', 'equity', 'drawdown'])

    # 解析所有交易的日期范围
    parsed_trades = []
    for t in trades:
        try:
            entry_dt = _parse_date(t['entry_date'])
            exit_dt = _parse_date(t['exit_date'])
            ret_pct = float(t.get('return_pct', 0.0))
            parsed_trades.append({
                'entry_date': entry_dt,
                'exit_date': exit_dt,
                'return_pct': ret_pct,
            })
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("跳过无效交易: %s, 原因: %s", t, exc)
            continue

    if not parsed_trades:
        return pd.DataFrame(columns=['date', 'equity', 'drawdown'])

    # 按卖出日期排序，依次叠加收益
    parsed_trades.sort(key=lambda x: x['exit_date'])

    min_date = min(t['entry_date'] for t in parsed_trades)
    max_date = max(t['exit_date'] for t in parsed_trades)

    # 构建日期索引（日历日）
    date_range = pd.date_range(start=min_date, end=max_date, freq='D')

    # 每日权益：在交易退出日将收益体现到权益上
    equity_series = pd.Series(initial_capital, index=date_range, dtype=np.float64)

    current_equity = initial_capital
    # 按退出日聚合收益
    exit_pnl = {}
    for t in parsed_trades:
        # 单笔绝对盈亏：按比例分摊到当时的资金上（简化模型）
        pnl = current_equity * (t['return_pct'] / 100.0) / max(
            1, len([x for x in parsed_trades if x['exit_date'] == t['exit_date']])
        )
        exit_date = t['exit_date']
        exit_pnl.setdefault(exit_date, 0.0)
        exit_pnl[exit_date] += pnl

    # 重新计算：按时间顺序逐日推进
    current_equity = initial_capital
    equity_values = []
    for d in date_range:
        dt = d.to_pydatetime().replace(tzinfo=None)
        if dt in exit_pnl:
            current_equity += exit_pnl[dt]
        equity_values.append(current_equity)

    equity_series = pd.Series(equity_values, index=date_range, dtype=np.float64)

    # 计算回撤
    running_max = equity_series.cummax()
    drawdown = ((equity_series - running_max) / running_max * 100.0).round(4)

    df = pd.DataFrame({
        'date': date_range,
        'equity': equity_series.values.round(2),
        'drawdown': drawdown.values,
    })

    return df


# ======================================================================
# 内部辅助函数
# ======================================================================

def _parse_date(date_val) -> datetime:
    """将各种日期格式统一转为 datetime 对象。"""
    if isinstance(date_val, datetime):
        return date_val
    if isinstance(date_val, pd.Timestamp):
        return date_val.to_pydatetime()
    if isinstance(date_val, str):
        for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
            try:
                return datetime.strptime(date_val, fmt)
            except ValueError:
                continue
        raise ValueError(f"无法解析日期: {date_val}")
    raise TypeError(f"不支持的日期类型: {type(date_val)}")


def _build_equity_from_returns(
    returns_pct: np.ndarray,
    initial_capital: float,
) -> np.ndarray:
    """
    从交易收益率序列构建权益曲线数组。

    假设每笔交易使用等额资金（简化模型），按顺序累乘。
    """
    # 将百分比转为倍数
    multipliers = 1.0 + returns_pct / 100.0
    equity = np.empty(len(multipliers) + 1, dtype=np.float64)
    equity[0] = initial_capital
    for i, m in enumerate(multipliers):
        equity[i + 1] = equity[i] * m
    return equity


def _calculate_max_drawdown(equity: np.ndarray) -> float:
    """
    计算最大回撤（百分比，返回负值）。

    Args:
        equity: 权益曲线数组

    Returns:
        最大回撤百分比（负值，如 -15.32 表示 15.32% 回撤）
    """
    if len(equity) < 2:
        return 0.0

    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max * 100.0
    return float(np.min(drawdowns))


def _calculate_sharpe(
    returns_pct: np.ndarray,
    hold_days_list: List[int],
) -> float:
    """
    计算夏普比率。

    将每笔交易收益率转化为等效日收益率，然后按标准年化公式计算。
    Sharpe = (mean_daily_return - daily_risk_free) / std_daily_return * sqrt(252)

    Args:
        returns_pct: 每笔交易收益率数组（%）
        hold_days_list: 每笔交易持有天数

    Returns:
        年化夏普比率
    """
    if len(returns_pct) < 2:
        return 0.0

    # 将每笔交易转化为日均收益率
    daily_returns = []
    for ret, days in zip(returns_pct, hold_days_list):
        trading_days = max(int(days * 5 / 7), 1)  # 粗略转换为交易日
        daily_ret = (1.0 + ret / 100.0) ** (1.0 / trading_days) - 1.0
        daily_returns.extend([daily_ret] * trading_days)

    daily_arr = np.array(daily_returns, dtype=np.float64)

    if len(daily_arr) < 2:
        return 0.0

    mean_daily = np.mean(daily_arr)
    std_daily = np.std(daily_arr, ddof=1)

    if std_daily < 1e-10:
        return 0.0

    daily_rf = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
    sharpe = (mean_daily - daily_rf) / std_daily * np.sqrt(TRADING_DAYS_PER_YEAR)

    return float(sharpe)
