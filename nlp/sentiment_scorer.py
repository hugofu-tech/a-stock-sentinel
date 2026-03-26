"""
多源情绪评分聚合器 — 支持时间衰减加权

将来自不同社交媒体源（东方财富、雪球、微博、拾字风云）的情绪数据进行
加权聚合，计算综合情绪评分，并提供异常检测与股票排名功能。
"""

import logging
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import SOCIAL_SOURCES, SENTIMENT_SUB_WEIGHTS
from storage.models import StockSentimentAggregate

logger = logging.getLogger(__name__)


class SentimentScorer:
    """多源情绪评分聚合与时间衰减计算"""

    def __init__(self):
        self.source_weights: Dict[str, float] = {
            name: cfg['weight']
            for name, cfg in SOCIAL_SOURCES.items()
        }

    # ------------------------------------------------------------------
    # 1. 多源加权聚合
    # ------------------------------------------------------------------

    def combine_sources(
        self,
        source_aggregates: Dict[str, StockSentimentAggregate],
    ) -> StockSentimentAggregate:
        """
        将多个来源的 StockSentimentAggregate 加权合并为一条综合记录。

        当部分数据源缺失时，自动按剩余来源的权重比例重新归一化（graceful degradation）。

        Parameters
        ----------
        source_aggregates : dict
            source_name -> StockSentimentAggregate，同一只股票、同一天的各来源数据。

        Returns
        -------
        StockSentimentAggregate
            source='combined' 的聚合记录。
        """
        if not source_aggregates:
            raise ValueError("source_aggregates 不能为空")

        # --- 计算有效权重（重新归一化） ---
        available_weights: Dict[str, float] = {}
        for src, agg in source_aggregates.items():
            w = self.source_weights.get(src, 0.0)
            if w > 0:
                available_weights[src] = w
            else:
                logger.warning("未知数据源 '%s'，已跳过", src)

        if not available_weights:
            raise ValueError("没有任何已知数据源提供数据")

        total_weight = sum(available_weights.values())
        norm_weights: Dict[str, float] = {
            src: w / total_weight for src, w in available_weights.items()
        }

        logger.debug(
            "数据源权重归一化: %s (缺失: %s)",
            {s: round(w, 4) for s, w in norm_weights.items()},
            set(self.source_weights) - set(available_weights),
        )

        # --- 加权聚合各字段 ---
        w_arr = np.array([norm_weights[s] for s in norm_weights])
        sources_ordered = list(norm_weights.keys())

        def _weighted_avg(field: str) -> float:
            vals = np.array([
                getattr(source_aggregates[s], field) for s in sources_ordered
            ], dtype=np.float64)
            return float(np.dot(w_arr, vals))

        combined_comment_volume = sum(
            source_aggregates[s].comment_volume for s in sources_ordered
        )

        # 取第一条记录的元信息
        ref = next(iter(source_aggregates.values()))

        combined = StockSentimentAggregate(
            stock_code=ref.stock_code,
            stock_name=ref.stock_name,
            date=ref.date,
            source='combined',
            comment_volume=combined_comment_volume,
            avg_sentiment=_weighted_avg('avg_sentiment'),
            bullish_ratio=_weighted_avg('bullish_ratio'),
            disagreement_index=_weighted_avg('disagreement_index'),
            sentiment_change=_weighted_avg('sentiment_change'),
            volume_change=_weighted_avg('volume_change'),
            weighted_sentiment=_weighted_avg('weighted_sentiment'),
            score=0.0,  # 最终分数由 calculate_sentiment_score 设置
        )

        logger.info(
            "[%s %s] 综合情绪: avg=%.3f, bullish=%.2f, volume=%d",
            combined.stock_code, combined.date,
            combined.avg_sentiment, combined.bullish_ratio,
            combined.comment_volume,
        )

        return combined

    # ------------------------------------------------------------------
    # 2. 时间衰减
    # ------------------------------------------------------------------

    def apply_time_decay(
        self,
        history: List[StockSentimentAggregate],
        decay_type: str = 'exponential',
        half_life_days: int = 3,
    ) -> float:
        """
        对历史情绪序列施加时间衰减，返回衰减加权平均情绪值。

        Parameters
        ----------
        history : list
            按日期排列的 StockSentimentAggregate 列表（不要求排序，内部按日期处理）。
        decay_type : str
            衰减类型，目前仅支持 'exponential'。
        half_life_days : int
            半衰期天数，默认 3 天（即 3 天前的数据权重为当天的一半）。

        Returns
        -------
        float
            时间衰减加权平均情绪 [-1, 1]。
        """
        if not history:
            return 0.0

        if decay_type != 'exponential':
            logger.warning("不支持的衰减类型 '%s'，回退到 exponential", decay_type)

        # 以最新日期为基准
        dates = [datetime.strptime(h.date, "%Y-%m-%d") for h in history]
        latest = max(dates)

        days_ago = np.array([
            (latest - d).days for d in dates
        ], dtype=np.float64)

        sentiments = np.array([
            h.avg_sentiment for h in history
        ], dtype=np.float64)

        # 指数衰减: weight = exp(-ln(2) * days_ago / half_life)
        decay_rate = math.log(2) / half_life_days
        weights = np.exp(-decay_rate * days_ago)

        total_weight = weights.sum()
        if total_weight == 0:
            return 0.0

        weighted_avg = float(np.dot(weights, sentiments) / total_weight)

        logger.debug(
            "时间衰减(half_life=%d): %d 天数据 -> 加权情绪=%.4f",
            half_life_days, len(history), weighted_avg,
        )

        return weighted_avg

    # ------------------------------------------------------------------
    # 3. 综合情绪评分 [0, 100]
    # ------------------------------------------------------------------

    def calculate_sentiment_score(
        self,
        combined: StockSentimentAggregate,
        history: Optional[List[StockSentimentAggregate]] = None,
        llm_score: Optional[float] = None,
    ) -> float:
        """
        计算最终情绪评分 [0, 100]。

        Parameters
        ----------
        combined : StockSentimentAggregate
            聚合后的综合情绪数据（source='combined' 或单源）。
        history : list, optional
            历史数据，用于时间衰减修正（暂留扩展接口，当前未直接使用）。
        llm_score : float, optional
            LLM 验证评分 [0, 100]。缺失时使用中性默认值 50。

        Returns
        -------
        float
            最终情绪评分 [0, 100]。
        """
        w = SENTIMENT_SUB_WEIGHTS

        # --- a. 情绪极性 (polarity) ---
        polarity_score = (combined.avg_sentiment + 1.0) * 50.0

        # --- b. 情绪动量 (momentum) ---
        sc = combined.sentiment_change
        if sc >= 0.3:
            momentum_score = 90.0 + (min(sc, 1.0) - 0.3) / 0.7 * 10.0
        elif sc >= 0.0:
            momentum_score = 50.0 + sc / 0.3 * 40.0
        elif sc >= -0.3:
            momentum_score = 10.0 + (sc + 0.3) / 0.3 * 40.0
        else:
            momentum_score = max(0.0, 10.0 + (sc + 0.3) / 0.7 * 10.0)

        # --- c. 评论量异常 (volume_surge) ---
        vc = combined.volume_change
        if vc > 1.0:
            volume_score = 80.0 + min((vc - 1.0) / 1.0, 1.0) * 20.0
        elif vc > 0.3:
            volume_score = 50.0 + (vc - 0.3) / 0.7 * 30.0
        elif vc >= -0.3:
            volume_score = 30.0 + (vc + 0.3) / 0.6 * 20.0
        else:
            volume_score = max(0.0, 30.0 + (vc + 0.3) / 0.7 * 30.0)

        # --- d. LLM 验证分 (llm_quality) ---
        llm_quality_score = llm_score if llm_score is not None else 50.0

        # --- 加权合计 ---
        raw_score = (
            w['polarity'] * polarity_score
            + w['momentum'] * momentum_score
            + w['volume_surge'] * volume_score
            + w['llm_quality'] * llm_quality_score
        )

        # --- 分歧度惩罚 ---
        penalty = 0.0
        if combined.disagreement_index > 0.3:
            # 线性惩罚：0.3 -> 0 分，1.0 -> 15 分
            penalty = min(
                15.0,
                (combined.disagreement_index - 0.3) / 0.7 * 15.0,
            )
            logger.debug(
                "[%s] 分歧度 %.3f > 0.3，扣减 %.1f 分",
                combined.stock_code, combined.disagreement_index, penalty,
            )

        final_score = float(np.clip(raw_score - penalty, 0.0, 100.0))

        logger.info(
            "[%s %s] 情绪评分: polarity=%.1f, momentum=%.1f, "
            "volume=%.1f, llm=%.1f, penalty=%.1f => %.1f",
            combined.stock_code, combined.date,
            polarity_score, momentum_score,
            volume_score, llm_quality_score, penalty,
            final_score,
        )

        return final_score

    # ------------------------------------------------------------------
    # 4. 股票排名
    # ------------------------------------------------------------------

    def rank_stocks(
        self,
        stock_scores: Dict[str, float],
    ) -> List[Tuple[str, float]]:
        """
        按情绪评分降序排列股票。

        Parameters
        ----------
        stock_scores : dict
            stock_code -> score。

        Returns
        -------
        list of (stock_code, score)
            按 score 降序排列。
        """
        ranked = sorted(stock_scores.items(), key=lambda x: x[1], reverse=True)
        logger.info(
            "股票情绪排名 Top-5: %s",
            [(code, round(s, 1)) for code, s in ranked[:5]],
        )
        return ranked

    # ------------------------------------------------------------------
    # 5. 异常检测
    # ------------------------------------------------------------------

    def detect_anomalies(
        self,
        combined: StockSentimentAggregate,
        history: List[StockSentimentAggregate],
    ) -> Dict[str, bool]:
        """
        检测情绪数据中的异常模式。

        Parameters
        ----------
        combined : StockSentimentAggregate
            当日综合情绪数据。
        history : list
            历史综合情绪数据列表。

        Returns
        -------
        dict
            各异常标志: volume_spike, sentiment_reversal,
            extreme_bullish, extreme_bearish, high_disagreement。
        """
        anomalies: Dict[str, bool] = {
            'volume_spike': False,
            'sentiment_reversal': False,
            'extreme_bullish': False,
            'extreme_bearish': False,
            'high_disagreement': False,
        }

        # --- volume_spike: 评论量 > 3 倍历史平均 ---
        if history:
            hist_volumes = np.array([
                h.comment_volume for h in history
            ], dtype=np.float64)
            avg_volume = hist_volumes.mean()
            if avg_volume > 0 and combined.comment_volume > 3.0 * avg_volume:
                anomalies['volume_spike'] = True
                logger.warning(
                    "[%s] 评论量激增: %d vs 历史均值 %.0f (%.1fx)",
                    combined.stock_code, combined.comment_volume,
                    avg_volume, combined.comment_volume / avg_volume,
                )

        # --- sentiment_reversal: 情绪与前一日符号相反 ---
        if history:
            # 按日期降序，取最近一天
            sorted_hist = sorted(history, key=lambda h: h.date, reverse=True)
            yesterday = sorted_hist[0]
            if (
                yesterday.avg_sentiment != 0.0
                and combined.avg_sentiment != 0.0
                and np.sign(combined.avg_sentiment) != np.sign(yesterday.avg_sentiment)
            ):
                anomalies['sentiment_reversal'] = True
                logger.warning(
                    "[%s] 情绪反转: %.3f -> %.3f",
                    combined.stock_code,
                    yesterday.avg_sentiment,
                    combined.avg_sentiment,
                )

        # --- extreme_bullish / extreme_bearish ---
        if combined.avg_sentiment > 0.7:
            anomalies['extreme_bullish'] = True
            logger.info(
                "[%s] 极度看多: avg_sentiment=%.3f",
                combined.stock_code, combined.avg_sentiment,
            )

        if combined.avg_sentiment < -0.5:
            anomalies['extreme_bearish'] = True
            logger.info(
                "[%s] 极度看空: avg_sentiment=%.3f",
                combined.stock_code, combined.avg_sentiment,
            )

        # --- high_disagreement ---
        if combined.disagreement_index > 0.4:
            anomalies['high_disagreement'] = True
            logger.info(
                "[%s] 高分歧: disagreement_index=%.3f",
                combined.stock_code, combined.disagreement_index,
            )

        if any(anomalies.values()):
            logger.info(
                "[%s %s] 检测到异常: %s",
                combined.stock_code, combined.date,
                [k for k, v in anomalies.items() if v],
            )

        return anomalies
