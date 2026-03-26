"""SnowNLP批量情绪分析器 — 中文社交帖子情绪分析"""

import logging
import statistics
from datetime import datetime
from typing import List, Optional

from snownlp import SnowNLP

from config import NLP_CONFIG
from storage.models import SentimentResult, SocialPost, StockSentimentAggregate

logger = logging.getLogger(__name__)


class SnowNLPAnalyzer:
    """基于SnowNLP的中文文本批量情绪分析器"""

    def __init__(self):
        self.bullish_threshold = NLP_CONFIG.get('bullish_threshold', 0.6)
        self.bearish_threshold = NLP_CONFIG.get('bearish_threshold', 0.4)
        # 将 SnowNLP 原始阈值 [0,1] 转为 normalized [-1,1] 空间用于看多判定
        self._bullish_normalized = self.bullish_threshold * 2 - 1  # 0.6 -> 0.2

    # ------------------------------------------------------------------
    # 单条分析
    # ------------------------------------------------------------------
    def analyze_post(self, post: SocialPost) -> SentimentResult:
        """分析单条帖子的情绪。

        Returns:
            SentimentResult，method='snownlp'
        """
        text = post.text.strip() if post.text else ""

        # 空文本或过短文本
        if len(text) < 3:
            return SentimentResult(
                stock_code=post.stock_code,
                source=post.source,
                method="snownlp",
                raw_score=0.5,
                normalized_score=0.0,
                confidence=0.0,
                post_url=post.url,
                timestamp=datetime.now(),
            )

        try:
            raw_score = SnowNLP(text).sentiments  # [0, 1]
        except Exception as exc:
            logger.warning("SnowNLP分析失败 [%s]: %s", post.url, exc)
            return SentimentResult(
                stock_code=post.stock_code,
                source=post.source,
                method="snownlp",
                raw_score=0.5,
                normalized_score=0.0,
                confidence=0.0,
                post_url=post.url,
                timestamp=datetime.now(),
            )

        normalized_score = raw_score * 2 - 1  # [-1, 1]
        # 置信度：离 0.5 越远越高，最远 0.5 -> confidence=1
        confidence = abs(raw_score - 0.5) * 2  # [0, 1]

        return SentimentResult(
            stock_code=post.stock_code,
            source=post.source,
            method="snownlp",
            raw_score=round(raw_score, 4),
            normalized_score=round(normalized_score, 4),
            confidence=round(confidence, 4),
            post_url=post.url,
            timestamp=datetime.now(),
        )

    # ------------------------------------------------------------------
    # 批量分析
    # ------------------------------------------------------------------
    def analyze_posts(self, posts: List[SocialPost]) -> List[SentimentResult]:
        """批量分析帖子列表，自动去重（按 url 去重）。

        Returns:
            与去重后帖子一一对应的 SentimentResult 列表。
        """
        seen_urls: set = set()
        results: List[SentimentResult] = []

        for post in posts:
            # 按 URL 去重；无 URL 的帖子不去重
            if post.url:
                if post.url in seen_urls:
                    continue
                seen_urls.add(post.url)

            result = self.analyze_post(post)
            results.append(result)

        logger.info(
            "SnowNLP批量分析完成: 总帖子=%d, 去重后=%d",
            len(posts),
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # 聚合
    # ------------------------------------------------------------------
    def aggregate_sentiment(
        self,
        stock_code: str,
        stock_name: str,
        date: str,
        source: str,
        posts: List[SocialPost],
        results: List[SentimentResult],
        prev_aggregate: Optional[StockSentimentAggregate] = None,
    ) -> StockSentimentAggregate:
        """将单条分析结果聚合为 StockSentimentAggregate。

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            date: 日期 (YYYY-MM-DD)
            source: 来源标识
            posts: 帖子列表（用于 engagement_score 加权）
            results: 对应的情绪分析结果
            prev_aggregate: 前一日聚合（用于计算变化量）
        """
        if not results:
            return StockSentimentAggregate(
                stock_code=stock_code,
                stock_name=stock_name,
                date=date,
                source=source,
            )

        scores = [r.normalized_score for r in results]
        comment_volume = len(posts)

        # 均值
        avg_sentiment = statistics.mean(scores)

        # 看多比例：normalized_score > bullish_normalized (默认 0.2)
        bullish_count = sum(1 for s in scores if s > self._bullish_normalized)
        bullish_ratio = bullish_count / len(scores)

        # 分歧度（标准差）
        disagreement_index = statistics.pstdev(scores) if len(scores) > 1 else 0.0

        # 加权情绪（按 engagement_score 加权）
        weighted_sentiment = self._calc_weighted_sentiment(posts, results)

        # 变化量
        sentiment_change = 0.0
        volume_change = 0.0
        if prev_aggregate is not None:
            sentiment_change = avg_sentiment - prev_aggregate.avg_sentiment
            if prev_aggregate.comment_volume > 0:
                volume_change = (
                    (comment_volume - prev_aggregate.comment_volume)
                    / prev_aggregate.comment_volume
                )

        # 最终评分 [0, 100]
        score = self._calc_score(
            comment_volume=comment_volume,
            avg_sentiment=avg_sentiment,
            sentiment_change=sentiment_change,
            disagreement_index=disagreement_index,
        )

        return StockSentimentAggregate(
            stock_code=stock_code,
            stock_name=stock_name,
            date=date,
            source=source,
            comment_volume=comment_volume,
            avg_sentiment=round(avg_sentiment, 4),
            bullish_ratio=round(bullish_ratio, 4),
            disagreement_index=round(disagreement_index, 4),
            sentiment_change=round(sentiment_change, 4),
            volume_change=round(volume_change, 4),
            weighted_sentiment=round(weighted_sentiment, 4),
            score=round(score, 2),
        )

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------
    def analyze_stock(
        self,
        stock_code: str,
        stock_name: str,
        date: str,
        source: str,
        posts: List[SocialPost],
        prev_aggregate: Optional[StockSentimentAggregate] = None,
    ) -> StockSentimentAggregate:
        """一步完成：批量分析 + 聚合。"""
        results = self.analyze_posts(posts)
        return self.aggregate_sentiment(
            stock_code=stock_code,
            stock_name=stock_name,
            date=date,
            source=source,
            posts=posts,
            results=results,
            prev_aggregate=prev_aggregate,
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_weighted_sentiment(
        posts: List[SocialPost],
        results: List[SentimentResult],
    ) -> float:
        """按帖子 engagement_score 加权计算情绪均值。"""
        if not results:
            return 0.0

        # 建立 url -> engagement 映射
        url_to_engagement: dict = {}
        for post in posts:
            if post.url:
                url_to_engagement[post.url] = post.engagement_score

        total_weight = 0.0
        weighted_sum = 0.0

        for result in results:
            weight = url_to_engagement.get(result.post_url, 1.0)
            # 保证最低权重为 1，避免零权重
            weight = max(weight, 1.0)
            weighted_sum += result.normalized_score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0
        return weighted_sum / total_weight

    @staticmethod
    def _calc_score(
        comment_volume: int,
        avg_sentiment: float,
        sentiment_change: float,
        disagreement_index: float,
    ) -> float:
        """计算最终情绪评分 [0, 100]。

        组成部分:
          - volume_component    (0-25):  评论量的百分位映射
          - polarity_component  (0-35):  情绪极性映射
          - momentum_component  (0-25):  情绪动量映射
          - disagreement_penalty(0~-15): 高分歧扣分
        """
        # --- volume_component (0-25) ---
        # 使用对数映射：1条->0, ~50条->~15, 200+条->25
        import math
        if comment_volume <= 0:
            volume_component = 0.0
        else:
            volume_component = min(25.0, 25.0 * math.log1p(comment_volume) / math.log1p(200))

        # --- polarity_component (0-35) ---
        # avg_sentiment [-1, 1] -> [0, 35]
        polarity_component = (avg_sentiment + 1) / 2 * 35  # linear

        # --- momentum_component (0-25) ---
        # sentiment_change [-2, 2] (理论) -> [0, 25]
        # 正向变化给高分，负向变化给低分
        clamped_change = max(-1.0, min(1.0, sentiment_change))
        momentum_component = (clamped_change + 1) / 2 * 25

        # --- disagreement_penalty (0 to -15) ---
        # disagreement_index 属于 [0, 1]（标准差），高分歧扣分
        penalty = min(15.0, disagreement_index * 15.0)
        disagreement_penalty = -penalty

        raw_score = (
            volume_component
            + polarity_component
            + momentum_component
            + disagreement_penalty
        )
        return max(0.0, min(100.0, raw_score))
