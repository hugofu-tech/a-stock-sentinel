"""
统一评分引擎 — 替代旧版 ProfessionalSentimentModel

综合技术面(30%)、资金面(20%)、社交情绪(40%)、风险调整(10%)
四个维度对候选股票进行评分，生成买卖信号与推荐列表。
"""

import logging
import math
from typing import List, Optional

import pandas as pd

from config import SCORE_WEIGHTS, STOCK_FILTER, TRADING_CONFIG
from storage.models import StockCandidate

logger = logging.getLogger(__name__)


class SentimentStockScorer:
    """多维度加权评分引擎

    评分体系:
      - technical  30%: 涨跌幅、换手率、量比、成交额
      - capital    20%: 资金强度、量价配合
      - sentiment  40%: 社交情绪（由外部传入）
      - risk_adj   10%: 风险调整（分歧、隔夜、流动性）

    所有子分数归一化到 [0, 100]，总分经加权后 clamp 到 [0, 100]。
    """

    def __init__(self):
        self.weights = SCORE_WEIGHTS
        self.filters = STOCK_FILTER
        self.trading = TRADING_CONFIG

    # ------------------------------------------------------------------
    # 1. 股票池过滤
    # ------------------------------------------------------------------

    def filter_universe(self, all_stocks_df: pd.DataFrame) -> pd.DataFrame:
        """从 akshare ``stock_zh_a_spot_em()`` 的原始 DataFrame 中筛选候选股。

        预期列名（东财实时行情）:
            代码, 名称, 最新价, 涨跌幅, 换手率, 量比, 流通市值, 成交额, ...

        Returns:
            过滤后的 DataFrame（行数可能为 0）。
        """
        if all_stocks_df is None or all_stocks_df.empty:
            logger.warning("filter_universe: 输入 DataFrame 为空")
            return pd.DataFrame()

        df = all_stocks_df.copy()
        initial_count = len(df)

        # ---- 数值列安全转换 ----
        numeric_cols = ["最新价", "涨跌幅", "换手率", "量比", "流通市值", "成交额"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # ---- ST 过滤 ----
        if self.filters.get("exclude_st", True) and "名称" in df.columns:
            before = len(df)
            df = df[~df["名称"].str.contains("ST|\\*ST", case=False, na=False)]
            logger.debug("排除ST: %d -> %d", before, len(df))

        # ---- 价格过滤 ----
        if "最新价" in df.columns:
            min_price = self.filters.get("min_price", 0)
            max_price = self.filters.get("max_price", 9999)
            df = df[df["最新价"].between(min_price, max_price)]

        # ---- 流通市值过滤（亿元） ----
        if "流通市值" in df.columns:
            # akshare 流通市值单位为元，需转换
            cap_col = df["流通市值"].copy()
            # 如果最大值 > 1e6 说明单位是元，转亿
            if cap_col.max() > 1e6:
                cap_col = cap_col / 1e8
            min_cap = self.filters.get("min_market_cap", 0)
            max_cap = self.filters.get("max_market_cap", 9999)
            df = df[cap_col.between(min_cap, max_cap)]

        # ---- 换手率过滤 ----
        if "换手率" in df.columns:
            min_turnover = self.filters.get("min_turnover_avg10", 0)
            max_turnover = self.filters.get("max_turnover_avg10", 100)
            df = df[df["换手率"].between(min_turnover, max_turnover)]

        # ---- 涨停排除 ----
        if self.filters.get("exclude_limit_up", True) and "涨跌幅" in df.columns:
            df = df[df["涨跌幅"] < 9.9]

        # ---- 次新股排除（代码前缀粗略判断：实际需上市日期，此处占位） ----
        # 完整实现需要 IPO 日期数据；此处仅记录配置值
        _new_days = self.filters.get("exclude_new_stock_days", 30)
        # TODO: 对接上市日期字段做精确过滤

        # ---- 跳空高开排除 ----
        gap_limit = self.trading.get("avoid_gap_up_pct", 3.0)
        if "涨跌幅" in df.columns:
            df = df[df["涨跌幅"] <= gap_limit * 3]  # 宽松预过滤；精确过滤在评分阶段

        logger.info(
            "filter_universe: %d -> %d (保留 %.1f%%)",
            initial_count, len(df),
            len(df) / max(initial_count, 1) * 100,
        )
        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    # 2. 技术面评分 [0, 100]
    # ------------------------------------------------------------------

    def score_technical(self, row) -> float:
        """技术面评分。

        Args:
            row: dict-like，需包含 涨跌幅, 换手率, 量比, 成交额 等字段。

        Returns:
            float [0, 100]
        """
        score = 0.0

        # -- 涨跌幅 (0-35) --
        change = float(row.get("涨跌幅", 0) or 0)
        if change >= 9.9:
            score += 35.0
        elif change >= 5.0:
            score += 25.0 + (change - 5.0) / 4.9 * 10.0
        elif change >= 2.0:
            score += 15.0 + (change - 2.0) / 3.0 * 10.0
        elif change > 0:
            score += change / 2.0 * 15.0
        elif change >= -2.0:
            score += max(0.0, 8.0 + change * 4.0)
        # change < -2: 0

        # -- 换手率 (0-25) --
        turnover = float(row.get("换手率", 0) or 0)
        if turnover >= 20.0:
            score += 25.0
        elif turnover >= 10.0:
            score += 18.0 + (turnover - 10.0) / 10.0 * 7.0
        elif turnover >= 3.0:
            score += 8.0 + (turnover - 3.0) / 7.0 * 10.0
        elif turnover >= 1.0:
            score += (turnover - 1.0) / 2.0 * 8.0
        # turnover < 1: 0

        # -- 量比 (0-25) --
        vol_ratio = float(row.get("量比", 1) or 1)
        if vol_ratio >= 3.0:
            score += 25.0
        elif vol_ratio >= 1.5:
            score += 15.0 + (vol_ratio - 1.5) / 1.5 * 10.0
        elif vol_ratio >= 0.8:
            score += (vol_ratio - 0.8) / 0.7 * 15.0
        # vol_ratio < 0.8: 0

        # -- 成交额 (0-15) -- 单位：亿元
        amount_raw = float(row.get("成交额", 0) or 0)
        # akshare 成交额单位为元，转亿
        amount = amount_raw / 1e8 if amount_raw > 1e6 else amount_raw
        if amount >= 10.0:
            score += 15.0
        elif amount >= 5.0:
            score += 10.0 + (amount - 5.0) / 5.0 * 5.0
        elif amount >= 1.0:
            score += 4.0 + (amount - 1.0) / 4.0 * 6.0
        elif amount > 0:
            score += amount / 1.0 * 4.0

        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    # 3. 资金面评分 [0, 100]
    # ------------------------------------------------------------------

    def score_capital(self, row) -> float:
        """资金面评分。

        资金强度 = 量比 * 0.6 + 换手率 * 0.4
        量价配合: 涨幅为正且量比放大时给予额外加分。

        Returns:
            float [0, 100]
        """
        score = 0.0

        vol_ratio = float(row.get("量比", 1) or 1)
        turnover = float(row.get("换手率", 0) or 0)
        change = float(row.get("涨跌幅", 0) or 0)

        # -- 资金强度 (0-60) --
        strength = vol_ratio * 0.6 + turnover * 0.4
        # 归一化：strength 通常在 0-20 区间
        normalized = strength / 10.0  # [0, ~2+]
        if normalized >= 2.0:
            score += 60.0
        elif normalized >= 1.0:
            score += 30.0 + (normalized - 1.0) * 30.0
        else:
            score += normalized * 30.0

        # -- 量价配合 (0-40) --
        if change > 3.0 and vol_ratio > 2.0:
            score += 40.0
        elif change > 2.0 and vol_ratio > 1.5:
            score += 32.0
        elif change > 0 and vol_ratio > 1.5:
            score += 25.0
        elif change > 0 and vol_ratio > 1.0:
            score += 18.0
        elif change > 0:
            score += 10.0
        elif change > -1.0 and vol_ratio < 1.0:
            # 缩量微跌：资金可能在暗中吸筹
            score += 8.0
        # 放量下跌：不加分

        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    # 4. 加权总分
    # ------------------------------------------------------------------

    def calculate_total_score(
        self,
        technical: float,
        capital: float,
        sentiment: float,
        risk_adj: float,
    ) -> float:
        """加权计算总分，clamp 到 [0, 100]。

        Args:
            technical: 技术面 [0, 100]
            capital:   资金面 [0, 100]
            sentiment: 情绪面 [0, 100]
            risk_adj:  风险调整 [-20, 0]（负值，扣分项）
        """
        w = self.weights
        raw = (
            technical * w.get("technical", 0.30)
            + capital * w.get("capital", 0.20)
            + sentiment * w.get("sentiment", 0.40)
            + risk_adj * w.get("risk_adjustment", 0.10)
        )
        return max(0.0, min(100.0, round(raw, 2)))

    # ------------------------------------------------------------------
    # 5. 风险调整 [-20, 0]
    # ------------------------------------------------------------------

    def apply_risk_adjustment(self, candidate: StockCandidate) -> float:
        """计算风险扣分项（取值 [-20, 0]，越小越差）。

        三类风险:
          1. 分歧度惩罚 —— 社交情绪内部分歧大
          2. T+1 隔夜风险 —— 当日涨幅过大（>7%）增加次日回调概率
          3. 流动性风险 —— 换手率过低或市值过小

        Returns:
            float [-20, 0]
        """
        penalty = 0.0

        # --- 1. 分歧度惩罚 (0 ~ -8) ---
        details = candidate.sentiment_details or {}
        disagreement = float(details.get("disagreement_index", 0))
        if disagreement > 0.4:
            # 强分歧
            penalty -= min(8.0, (disagreement - 0.4) / 0.6 * 8.0)
        elif disagreement > 0.25:
            penalty -= (disagreement - 0.25) / 0.15 * 3.0

        # --- 2. T+1 隔夜风险 (0 ~ -8) ---
        change = candidate.change_pct
        if change >= 9.5:
            penalty -= 8.0  # 涨停板，次日波动风险极高
        elif change >= 7.0:
            penalty -= 4.0 + (change - 7.0) / 2.5 * 4.0
        elif change >= 5.0:
            penalty -= (change - 5.0) / 2.0 * 4.0

        # --- 3. 流动性风险 (0 ~ -4) ---
        if candidate.turnover_rate < 1.0:
            penalty -= 4.0
        elif candidate.turnover_rate < 2.0:
            penalty -= (2.0 - candidate.turnover_rate) / 1.0 * 3.0

        if candidate.market_cap < 20.0:
            # 流通市值低于 20 亿
            penalty -= min(3.0, (20.0 - candidate.market_cap) / 10.0 * 3.0)

        result = max(-20.0, min(0.0, penalty))

        logger.debug(
            "[%s] 风险调整=%.1f (分歧=%.2f, 涨幅=%.1f%%, 换手=%.1f%%, 市值=%.0f亿)",
            candidate.stock_code, result, disagreement,
            change, candidate.turnover_rate, candidate.market_cap,
        )

        return round(result, 2)

    # ------------------------------------------------------------------
    # 6. 信号生成
    # ------------------------------------------------------------------

    def generate_signal(self, candidate: StockCandidate) -> str:
        """根据总分生成交易信号。

        Returns:
            "STRONG_BUY" | "BUY" | "WATCH" | "PASS"
        """
        total = candidate.total_score
        if total >= 75:
            return "STRONG_BUY"
        elif total >= 60:
            return "BUY"
        elif total >= 45:
            return "WATCH"
        else:
            return "PASS"

    # ------------------------------------------------------------------
    # 7. 生成推荐列表
    # ------------------------------------------------------------------

    def generate_recommendations(
        self,
        candidates: List[StockCandidate],
    ) -> List[StockCandidate]:
        """对候选列表排序、截断、生成推荐理由。

        流程:
          1. 按 total_score 降序排列
          2. 取前 N 名（max_buy_recommendations）
          3. 为每只股票填充 signal / reason / stop_loss / take_profit

        Returns:
            推荐列表（已排序、已截断）。
        """
        if not candidates:
            logger.info("generate_recommendations: 无候选股票")
            return []

        # 排序
        ranked = sorted(candidates, key=lambda c: c.total_score, reverse=True)

        max_n = self.trading.get("max_buy_recommendations", 3)
        top = ranked[:max_n]

        for rank, cand in enumerate(top, 1):
            # 生成信号
            cand.signal = self.generate_signal(cand)

            # 止损止盈
            cand.stop_loss_pct = self.trading.get("stop_loss_pct", -5.0)
            cand.take_profit_pct = self.trading.get("take_profit_pct", 10.0)

            # 建议持有天数
            if cand.total_score >= 75:
                cand.suggested_hold_days = 5
            elif cand.total_score >= 60:
                cand.suggested_hold_days = 3
            else:
                cand.suggested_hold_days = 2

            # 生成推荐理由
            cand.reason = self._build_reason(cand, rank)

            logger.info(
                "[#%d] %s(%s) 总分=%.1f 信号=%s | 技术=%.1f 资金=%.1f "
                "情绪=%.1f 风险=%.1f",
                rank, cand.stock_name, cand.stock_code,
                cand.total_score, cand.signal,
                cand.technical_score, cand.capital_score,
                cand.sentiment_score, cand.risk_adjustment,
            )

        return top

    # ------------------------------------------------------------------
    # 辅助: 构建推荐理由
    # ------------------------------------------------------------------

    @staticmethod
    def _build_reason(cand: StockCandidate, rank: int) -> str:
        """为候选股票拼接人类可读的推荐理由。"""
        parts: List[str] = []

        # 信号强度
        if cand.signal == "STRONG_BUY":
            parts.append(f"第{rank}名 | 强烈买入")
        elif cand.signal == "BUY":
            parts.append(f"第{rank}名 | 买入")
        else:
            parts.append(f"第{rank}名 | 关注")

        # 技术面亮点
        if cand.technical_score >= 70:
            parts.append("技术面强势")
        elif cand.technical_score >= 50:
            parts.append("技术面良好")

        # 资金面亮点
        if cand.capital_score >= 70:
            parts.append("资金积极流入")
        elif cand.capital_score >= 50:
            parts.append("资金面配合")

        # 情绪面亮点
        if cand.sentiment_score >= 75:
            parts.append("社交情绪高涨")
        elif cand.sentiment_score >= 55:
            parts.append("情绪偏多")

        # 风险提示
        if cand.risk_adjustment <= -10:
            parts.append("注意风险较高")
        elif cand.risk_adjustment <= -5:
            parts.append("存在一定风险")

        # 价格信息
        parts.append(
            f"现价{cand.price:.2f}元 涨幅{cand.change_pct:+.2f}%"
        )

        # 止损止盈
        parts.append(
            f"止损{cand.stop_loss_pct}%/止盈{cand.take_profit_pct}%"
        )

        return " | ".join(parts)

    # ------------------------------------------------------------------
    # 便捷: 一步完成评分
    # ------------------------------------------------------------------

    def score_candidate(
        self,
        row,
        sentiment_score: float = 50.0,
        sentiment_details: Optional[dict] = None,
        llm_summary: str = "",
    ) -> StockCandidate:
        """从行情数据行一步生成 StockCandidate（含全部评分）。

        Args:
            row: dict-like，东财行情数据行。
            sentiment_score: 社交情绪评分 [0, 100]（由 NLP 管线提供）。
            sentiment_details: 情绪细节字典。
            llm_summary: LLM 分析摘要。

        Returns:
            填充完毕的 StockCandidate。
        """
        code = str(row.get("代码", row.get("stock_code", "")))
        name = str(row.get("名称", row.get("stock_name", "")))
        price = float(row.get("最新价", row.get("price", 0)) or 0)
        change_pct = float(row.get("涨跌幅", row.get("change_pct", 0)) or 0)
        turnover_rate = float(row.get("换手率", row.get("turnover_rate", 0)) or 0)
        vol_ratio = float(row.get("量比", row.get("volume_ratio", 1)) or 1)

        # 市值（亿）
        raw_cap = float(row.get("流通市值", row.get("market_cap", 0)) or 0)
        market_cap = raw_cap / 1e8 if raw_cap > 1e6 else raw_cap

        # 评分
        tech = self.score_technical(row)
        cap = self.score_capital(row)

        candidate = StockCandidate(
            stock_code=code,
            stock_name=name,
            price=price,
            change_pct=change_pct,
            market_cap=market_cap,
            turnover_rate=turnover_rate,
            volume_ratio=vol_ratio,
            technical_score=round(tech, 2),
            capital_score=round(cap, 2),
            sentiment_score=round(sentiment_score, 2),
            sentiment_details=sentiment_details or {},
            llm_summary=llm_summary,
        )

        # 风险调整
        candidate.risk_adjustment = self.apply_risk_adjustment(candidate)

        # 总分
        candidate.total_score = self.calculate_total_score(
            candidate.technical_score,
            candidate.capital_score,
            candidate.sentiment_score,
            candidate.risk_adjustment,
        )

        # 信号
        candidate.signal = self.generate_signal(candidate)

        return candidate
