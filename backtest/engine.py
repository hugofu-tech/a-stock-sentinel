"""
回测引擎模块

实现 A 股 T+1 规则的回测引擎，支持佣金/印花税/滑点、止损止盈、
涨跌停判断等。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import BACKTEST_CONFIG, TRADING_CONFIG
from backtest.metrics import calculate_metrics, calculate_daily_equity

logger = logging.getLogger(__name__)

# 涨跌停幅度（普通 A 股 ±10%）
LIMIT_PCT = 10.0


class BacktestEngine:
    """
    A 股回测引擎。

    核心规则:
        - T+1: 买入信号日 T，次交易日 T+1 以开盘价买入
        - 持有 default_hold_days 个交易日后，在退出日以开盘价卖出
        - 同时最多持有 max_buy_recommendations 只股票
        - 每日检查止损/止盈，触发时次日开盘卖出
        - 涨跌停（±10%）时不交易
        - 仅在开盘价（09:30）交易
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化回测引擎。

        Args:
            config: 可选配置字典，覆盖默认的 BACKTEST_CONFIG / TRADING_CONFIG
        """
        cfg = {**BACKTEST_CONFIG, **TRADING_CONFIG}
        if config:
            cfg.update(config)

        self.commission_rate: float = cfg.get('commission_rate', 0.0003)
        self.stamp_tax_rate: float = cfg.get('stamp_tax_rate', 0.001)
        self.slippage_pct: float = cfg.get('slippage_pct', 0.001)
        self.initial_capital: float = cfg.get('initial_capital', 100000)
        self.benchmark: str = cfg.get('benchmark', '000300')

        self.max_positions: int = cfg.get('max_buy_recommendations', 3)
        self.default_hold_days: int = cfg.get('default_hold_days', 3)
        self.stop_loss_pct: float = cfg.get('stop_loss_pct', -5.0)
        self.take_profit_pct: float = cfg.get('take_profit_pct', 10.0)
        self.avoid_gap_up_pct: float = cfg.get('avoid_gap_up_pct', 3.0)

    # ==================================================================
    # 公开接口
    # ==================================================================

    def run(
        self,
        signals: List[Dict],
        price_data: pd.DataFrame,
        start_date: str,
        end_date: str,
    ) -> Dict:
        """
        执行回测。

        Args:
            signals: 信号列表，每条信号为 dict:
                - date:       信号日期 (str 'YYYY-MM-DD' 或 datetime)
                - stock_code: 股票代码
                - stock_name: 股票名称
                - score:      信号评分
                - signal:     信号类型（'BUY'）
            price_data: 行情 DataFrame，列:
                date, stock_code, open, high, low, close, volume
            start_date: 回测起始日期 (str 'YYYY-MM-DD')
            end_date:   回测截止日期 (str 'YYYY-MM-DD')

        Returns:
            dict: {
                'trades':       交易记录列表,
                'metrics':      绩效指标字典,
                'equity_curve': 日权益 DataFrame,
            }
        """
        # ---- 预处理 ----
        price_df = self._prepare_price_data(price_data)
        if price_df.empty:
            logger.error("行情数据为空，无法回测")
            return self._empty_result()

        trading_dates = sorted(price_df['date'].unique())
        start_dt = pd.Timestamp(start_date)
        end_dt = pd.Timestamp(end_date)

        # 按日期过滤交易日
        trading_dates = [d for d in trading_dates if start_dt <= d <= end_dt]
        if not trading_dates:
            logger.error("回测区间内无交易日")
            return self._empty_result()

        # 按日期和评分排序信号
        sorted_signals = self._prepare_signals(signals, start_dt, end_dt)

        # ---- 逐日推进 ----
        trades: List[Dict] = []
        open_positions: List[Dict] = []  # 当前持仓

        for sig in sorted_signals:
            sig_date = sig['_date']

            # 检查当天是否有空余仓位
            # 先清理已到期或已止损止盈的持仓
            open_positions, closed = self._check_exits(
                open_positions, sig_date, price_df, trading_dates
            )
            trades.extend(closed)

            if len(open_positions) >= self.max_positions:
                continue

            # T+1：在信号日的下一个交易日执行买入
            trade = self._execute_trade(sig, price_df, trading_dates)
            if trade is not None:
                open_positions.append(trade)

        # 回测结束，强制平仓剩余持仓
        for pos in open_positions:
            closed_trade = self._force_close(pos, price_df, trading_dates, end_dt)
            if closed_trade:
                trades.append(closed_trade)

        # ---- 计算指标 ----
        metrics = calculate_metrics(trades, self.initial_capital)
        equity_curve = calculate_daily_equity(trades, self.initial_capital)

        return {
            'trades': trades,
            'metrics': metrics,
            'equity_curve': equity_curve,
        }

    def print_summary(self, result: Dict) -> None:
        """打印格式化的回测摘要。"""
        metrics = result.get('metrics', {})
        trades = result.get('trades', [])

        print("=" * 60)
        print("              回测绩效摘要")
        print("=" * 60)
        print(f"  总交易次数:        {metrics.get('total_trades', 0)}")
        print(f"  累计收益率:        {metrics.get('total_return', 0):.2f}%")
        print(f"  年化收益率:        {metrics.get('annualized_return', 0):.2f}%")
        print(f"  夏普比率:          {metrics.get('sharpe_ratio', 0):.4f}")
        print(f"  最大回撤:          {metrics.get('max_drawdown', 0):.2f}%")
        print(f"  胜率:              {metrics.get('win_rate', 0):.2f}%")
        pf = metrics.get('profit_factor', 0)
        pf_str = f"{pf:.4f}" if np.isfinite(pf) else "inf"
        print(f"  盈亏比:            {pf_str}")
        print(f"  平均收益:          {metrics.get('avg_return', 0):.4f}%")
        print(f"  平均持仓天数:      {metrics.get('avg_hold_days', 0):.1f}")
        print(f"  最佳交易:          {metrics.get('best_trade', 0):.4f}%")
        print(f"  最差交易:          {metrics.get('worst_trade', 0):.4f}%")

        if metrics.get('benchmark_return') is not None:
            print(f"  基准收益率:        {metrics['benchmark_return']:.2f}%")
            alpha = metrics.get('total_return', 0) - metrics['benchmark_return']
            print(f"  超额收益:          {alpha:.2f}%")

        print("=" * 60)

        if trades:
            print("\n最近 5 笔交易:")
            print(f"  {'股票':>10s}  {'买入日':>12s}  {'卖出日':>12s}  {'收益%':>8s}")
            print("  " + "-" * 48)
            for t in trades[-5:]:
                code = t.get('stock_code', '')
                entry = str(t.get('entry_date', ''))[:10]
                exit_ = str(t.get('exit_date', ''))[:10]
                ret = t.get('return_pct', 0)
                print(f"  {code:>10s}  {entry:>12s}  {exit_:>12s}  {ret:>+8.2f}")

    # ==================================================================
    # 内部方法
    # ==================================================================

    def _prepare_price_data(self, price_data: pd.DataFrame) -> pd.DataFrame:
        """清洗并标准化行情数据。"""
        if price_data is None or price_data.empty:
            return pd.DataFrame()

        df = price_data.copy()

        # 确保列名小写
        df.columns = [c.lower().strip() for c in df.columns]

        required = {'date', 'stock_code', 'open', 'high', 'low', 'close', 'volume'}
        missing = required - set(df.columns)
        if missing:
            logger.error("行情数据缺少必要列: %s", missing)
            return pd.DataFrame()

        df['date'] = pd.to_datetime(df['date'])
        for col in ('open', 'high', 'low', 'close', 'volume'):
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df.dropna(subset=['date', 'stock_code', 'open', 'close'])
        df = df.sort_values(['stock_code', 'date']).reset_index(drop=True)

        # 计算前日收盘（用于涨跌停判断）
        df['prev_close'] = df.groupby('stock_code')['close'].shift(1)

        return df

    def _prepare_signals(
        self,
        signals: List[Dict],
        start_dt: pd.Timestamp,
        end_dt: pd.Timestamp,
    ) -> List[Dict]:
        """过滤并排序信号。"""
        result = []
        for s in signals:
            try:
                sig = dict(s)
                sig_date = pd.Timestamp(sig['date'])
                if sig_date < start_dt or sig_date > end_dt:
                    continue
                if sig.get('signal', '').upper() != 'BUY':
                    continue
                sig['_date'] = sig_date
                result.append(sig)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("跳过无效信号: %s, 原因: %s", s, exc)
                continue

        # 按日期升序，同日按评分降序
        result.sort(key=lambda x: (x['_date'], -float(x.get('score', 0))))
        return result

    def _execute_trade(
        self,
        signal: Dict,
        price_df: pd.DataFrame,
        trading_dates: list,
    ) -> Optional[Dict]:
        """
        根据信号执行一笔交易。

        T+1 规则：信号日 T 的下一个交易日 T+1 以开盘价买入。

        Returns:
            交易记录 dict，若无法执行则返回 None
        """
        sig_date = signal['_date']
        stock_code = signal['stock_code']

        # 找到信号日的下一个交易日作为买入日
        entry_date = self._next_trading_date(sig_date, trading_dates)
        if entry_date is None:
            logger.debug("信号 %s %s 无法找到买入交易日", stock_code, sig_date)
            return None

        # 获取买入日行情
        entry_row = self._get_price_row(price_df, stock_code, entry_date)
        if entry_row is None:
            logger.debug("股票 %s 在 %s 无行情数据", stock_code, entry_date)
            return None

        entry_open = float(entry_row['open'])
        prev_close = entry_row.get('prev_close')

        # 检查涨跌停
        if self._is_limit(entry_open, prev_close):
            logger.debug("股票 %s 在 %s 涨跌停，跳过", stock_code, entry_date)
            return None

        # 检查跳空高开
        if prev_close is not None and not np.isnan(prev_close) and prev_close > 0:
            gap_pct = (entry_open / prev_close - 1.0) * 100.0
            if gap_pct > self.avoid_gap_up_pct:
                logger.debug(
                    "股票 %s 在 %s 跳空高开 %.2f%%，跳过",
                    stock_code, entry_date, gap_pct,
                )
                return None

        # 买入成本（含佣金 + 滑点）
        buy_cost = self._apply_costs(entry_open, is_buy=True)

        # ---- 持仓期间逐日检查止损/止盈 ----
        exit_date = None
        exit_price = None
        exit_reason = 'hold_expire'

        # 从买入日之后开始算持有天数
        entry_idx = self._date_index(entry_date, trading_dates)
        if entry_idx is None:
            return None

        # 持有期交易日列表（不含买入日，T+1 当天不能卖）
        hold_start = entry_idx + 1
        hold_end = min(entry_idx + self.default_hold_days + 1, len(trading_dates))

        for i in range(hold_start, hold_end):
            check_date = trading_dates[i]
            row = self._get_price_row(price_df, stock_code, check_date)
            if row is None:
                continue

            day_high = float(row['high'])
            day_low = float(row['low'])
            day_close = float(row['close'])

            # 日内收益率（相对买入成本）
            high_ret = (day_high / buy_cost - 1.0) * 100.0
            low_ret = (day_low / buy_cost - 1.0) * 100.0

            # 止损检查（日内最低价触发）
            if low_ret <= self.stop_loss_pct:
                # 触发止损，次日开盘卖出
                next_td = self._next_trading_date(check_date, trading_dates)
                if next_td is not None:
                    sell_row = self._get_price_row(price_df, stock_code, next_td)
                    if sell_row is not None:
                        exit_date = next_td
                        exit_price = float(sell_row['open'])
                        exit_reason = 'stop_loss'
                        break
                # 如果找不到下一交易日，就在当日收盘价卖
                exit_date = check_date
                exit_price = day_close
                exit_reason = 'stop_loss'
                break

            # 止盈检查（日内最高价触发）
            if high_ret >= self.take_profit_pct:
                next_td = self._next_trading_date(check_date, trading_dates)
                if next_td is not None:
                    sell_row = self._get_price_row(price_df, stock_code, next_td)
                    if sell_row is not None:
                        exit_date = next_td
                        exit_price = float(sell_row['open'])
                        exit_reason = 'take_profit'
                        break
                exit_date = check_date
                exit_price = day_close
                exit_reason = 'take_profit'
                break

        # 如果持有期结束仍未退出，在持有期最后一天的下一交易日开盘卖出
        if exit_date is None:
            target_exit_idx = min(entry_idx + self.default_hold_days + 1, len(trading_dates) - 1)
            exit_date = trading_dates[target_exit_idx]
            row = self._get_price_row(price_df, stock_code, exit_date)
            if row is not None:
                exit_price = float(row['open'])
            else:
                # 向前找最近有行情的交易日
                for j in range(target_exit_idx, entry_idx, -1):
                    row = self._get_price_row(price_df, stock_code, trading_dates[j])
                    if row is not None:
                        exit_date = trading_dates[j]
                        exit_price = float(row['close'])
                        break

        if exit_price is None:
            logger.debug("股票 %s 无法确定卖出价格，跳过", stock_code)
            return None

        # 检查卖出时是否涨跌停
        exit_row = self._get_price_row(price_df, stock_code, exit_date)
        if exit_row is not None:
            exit_prev_close = exit_row.get('prev_close')
            if self._is_limit(exit_price, exit_prev_close):
                logger.debug("股票 %s 在 %s 卖出时涨跌停，延后", stock_code, exit_date)
                # 尝试延后一天卖出
                next_td = self._next_trading_date(exit_date, trading_dates)
                if next_td is not None:
                    next_row = self._get_price_row(price_df, stock_code, next_td)
                    if next_row is not None:
                        exit_date = next_td
                        exit_price = float(next_row['open'])

        # 卖出实际到手价（扣佣金 + 印花税 + 滑点）
        sell_net = self._apply_costs(exit_price, is_buy=False)

        return_pct = (sell_net / buy_cost - 1.0) * 100.0

        trade = {
            'stock_code': stock_code,
            'stock_name': signal.get('stock_name', ''),
            'entry_date': entry_date.strftime('%Y-%m-%d') if hasattr(entry_date, 'strftime') else str(entry_date)[:10],
            'exit_date': exit_date.strftime('%Y-%m-%d') if hasattr(exit_date, 'strftime') else str(exit_date)[:10],
            'entry_price': round(float(buy_cost), 4),
            'exit_price': round(float(sell_net), 4),
            'return_pct': round(float(return_pct), 4),
            'exit_reason': exit_reason,
            'signal_score': signal.get('score', 0),
        }

        logger.info(
            "交易: %s %s -> %s, 收益: %+.2f%% (%s)",
            stock_code, trade['entry_date'], trade['exit_date'],
            return_pct, exit_reason,
        )

        return trade

    def _apply_costs(self, price: float, is_buy: bool) -> float:
        """
        计算交易成本后的实际价格。

        Args:
            price: 原始成交价
            is_buy: True=买入, False=卖出

        Returns:
            含成本的实际价格
        """
        if is_buy:
            # 买入：价格上浮（佣金 + 滑点）
            return price * (1.0 + self.commission_rate + self.slippage_pct)
        else:
            # 卖出：价格下浮（佣金 + 印花税 + 滑点）
            return price * (1.0 - self.commission_rate - self.stamp_tax_rate - self.slippage_pct)

    def _check_exits(
        self,
        open_positions: List[Dict],
        current_date: pd.Timestamp,
        price_df: pd.DataFrame,
        trading_dates: list,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        检查持仓中是否有需要平仓的（已过期的）。

        注意：止损/止盈在 _execute_trade 内已处理，这里主要清理
        已经有 exit_date 的持仓记录。

        Returns:
            (仍持有的仓位列表, 已平仓交易列表)
        """
        still_open = []
        closed = []

        for pos in open_positions:
            exit_dt = pd.Timestamp(pos.get('exit_date', '2099-12-31'))
            if exit_dt <= current_date:
                closed.append(pos)
            else:
                still_open.append(pos)

        return still_open, closed

    def _force_close(
        self,
        position: Dict,
        price_df: pd.DataFrame,
        trading_dates: list,
        end_dt: pd.Timestamp,
    ) -> Optional[Dict]:
        """回测结束时强制平仓。如果已有退出信息则直接返回。"""
        if position.get('exit_date') and position.get('return_pct') is not None:
            return position

        stock_code = position.get('stock_code', '')
        # 找到 end_dt 或之前最近的交易日
        close_date = None
        close_price = None

        for d in reversed(trading_dates):
            if d <= end_dt:
                row = self._get_price_row(price_df, stock_code, d)
                if row is not None:
                    close_date = d
                    close_price = float(row['close'])
                    break

        if close_price is None:
            return None

        sell_net = self._apply_costs(close_price, is_buy=False)
        buy_cost = float(position.get('entry_price', close_price))
        return_pct = (sell_net / buy_cost - 1.0) * 100.0 if buy_cost > 0 else 0.0

        position['exit_date'] = close_date.strftime('%Y-%m-%d') if hasattr(close_date, 'strftime') else str(close_date)[:10]
        position['exit_price'] = round(sell_net, 4)
        position['return_pct'] = round(return_pct, 4)
        position['exit_reason'] = 'force_close'

        return position

    # ==================================================================
    # 工具方法
    # ==================================================================

    def _next_trading_date(
        self,
        current: pd.Timestamp,
        trading_dates: list,
    ) -> Optional[pd.Timestamp]:
        """获取 current 之后的下一个交易日。"""
        for d in trading_dates:
            if d > current:
                return d
        return None

    def _date_index(
        self,
        date: pd.Timestamp,
        trading_dates: list,
    ) -> Optional[int]:
        """获取日期在交易日列表中的索引。"""
        try:
            return trading_dates.index(date)
        except ValueError:
            # 找最近的
            for i, d in enumerate(trading_dates):
                if d >= date:
                    return i
            return None

    def _get_price_row(
        self,
        price_df: pd.DataFrame,
        stock_code: str,
        date: pd.Timestamp,
    ) -> Optional[pd.Series]:
        """获取某只股票某日的行情数据行。"""
        mask = (price_df['stock_code'] == stock_code) & (price_df['date'] == date)
        rows = price_df.loc[mask]
        if rows.empty:
            return None
        return rows.iloc[0]

    @staticmethod
    def _is_limit(
        price: float,
        prev_close: Optional[float],
    ) -> bool:
        """
        判断是否涨跌停。

        涨跌停定义：开盘价/当前价 相对前收盘 变动超过 ±10%（含）。
        """
        if prev_close is None or np.isnan(prev_close) or prev_close <= 0:
            return False
        change_pct = abs(price / prev_close - 1.0) * 100.0
        return change_pct >= LIMIT_PCT - 0.01  # 容差

    def _empty_result(self) -> Dict:
        """返回空回测结果。"""
        return {
            'trades': [],
            'metrics': calculate_metrics([]),
            'equity_curve': pd.DataFrame(columns=['date', 'equity', 'drawdown']),
        }
