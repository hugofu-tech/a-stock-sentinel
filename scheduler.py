"""
双管线调度器 — 夜间采集 + 晨间评分

夜间管线 (~22:00 北京时间):
  1. 获取股票池
  2. 从社交媒体批量采集帖子
  3. SnowNLP 批量情绪分析
  4. 存储到 SQLite

晨间管线 (~08:30 北京时间):
  1. 加载夜间数据
  2. 可选：增量采集隔夜帖子
  3. SentimentStockScorer 综合评分
  4. LLM 验证 Top-N 候选
  5. 生成买/卖推荐
  6. 发送通知
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz

from config import (
    DB_PATH,
    FEISHU_WEBHOOK_URL,
    LLM_API_KEY,
    NLP_CONFIG,
    SOCIAL_SOURCES,
    STOCK_FILTER,
    TRADING_CONFIG,
)
from storage.models import (
    DailyRecommendation,
    StockCandidate,
    StockSentimentAggregate,
)

logger = logging.getLogger(__name__)

BEIJING_TZ = pytz.timezone("Asia/Shanghai")

# ---------------------------------------------------------------------------
# 默认股票列表（akshare 不可用时的兜底方案）
# ---------------------------------------------------------------------------
_DEFAULT_STOCKS = [
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


class SentimentScheduler:
    """双管线调度器

    管理夜间采集管线与晨间评分管线，协调各组件完成端到端工作流。
    所有外部依赖（akshare、社交媒体爬虫、LLM）均做优雅降级处理。
    """

    def __init__(self):
        """初始化所有组件，失败的组件标记为 None 并记录警告。"""

        # -- SourceManager（社交媒体数据源编排） --
        self.source_manager = None
        try:
            from social.source_manager import SourceManager
            self.source_manager = SourceManager()
            logger.info("[Scheduler] SourceManager 初始化成功")
        except Exception as exc:
            logger.warning("[Scheduler] SourceManager 初始化失败: %s", exc)

        # -- SnowNLPAnalyzer --
        self.nlp_analyzer = None
        try:
            from nlp.snownlp_analyzer import SnowNLPAnalyzer
            self.nlp_analyzer = SnowNLPAnalyzer()
            logger.info("[Scheduler] SnowNLPAnalyzer 初始化成功")
        except Exception as exc:
            logger.warning("[Scheduler] SnowNLPAnalyzer 初始化失败: %s", exc)

        # -- SentimentScorer（多源聚合） --
        self.sentiment_scorer = None
        try:
            from nlp.sentiment_scorer import SentimentScorer
            self.sentiment_scorer = SentimentScorer()
            logger.info("[Scheduler] SentimentScorer 初始化成功")
        except Exception as exc:
            logger.warning("[Scheduler] SentimentScorer 初始化失败: %s", exc)

        # -- SentimentStore（SQLite） --
        self.store = None
        try:
            from storage.sqlite_store import SentimentStore
            self.store = SentimentStore(db_path=DB_PATH)
            logger.info("[Scheduler] SentimentStore 初始化成功 (%s)", DB_PATH)
        except Exception as exc:
            logger.warning("[Scheduler] SentimentStore 初始化失败: %s", exc)

        # -- SentimentStockScorer（综合评分引擎） --
        self.stock_scorer = None
        try:
            from sentiment_stock_scorer import SentimentStockScorer
            self.stock_scorer = SentimentStockScorer()
            logger.info("[Scheduler] SentimentStockScorer 初始化成功")
        except Exception as exc:
            logger.warning("[Scheduler] SentimentStockScorer 初始化失败: %s", exc)

        # -- LLMAnalyzer（可选） --
        self.llm_analyzer = None
        if LLM_API_KEY:
            try:
                # LLMAnalyzer 可能尚未实现；做好兜底
                from nlp.llm_analyzer import LLMAnalyzer  # type: ignore
                self.llm_analyzer = LLMAnalyzer()
                logger.info("[Scheduler] LLMAnalyzer 初始化成功")
            except ImportError:
                logger.info("[Scheduler] LLMAnalyzer 模块未找到，跳过 LLM 验证")
            except Exception as exc:
                logger.warning("[Scheduler] LLMAnalyzer 初始化失败: %s", exc)
        else:
            logger.info("[Scheduler] 未配置 LLM_API_KEY，跳过 LLM 验证")

        # -- FeishuPusher（通知） --
        self.pusher = None
        try:
            from feishu_pusher import FeishuPusher
            self.pusher = FeishuPusher(webhook_url=FEISHU_WEBHOOK_URL)
            logger.info("[Scheduler] FeishuPusher 初始化成功")
        except Exception as exc:
            logger.warning("[Scheduler] FeishuPusher 初始化失败: %s", exc)

        logger.info(
            "[Scheduler] 初始化完成 | 组件状态: "
            "SourceManager=%s, NLP=%s, Scorer=%s, Store=%s, StockScorer=%s, "
            "LLM=%s, Pusher=%s",
            self.source_manager is not None,
            self.nlp_analyzer is not None,
            self.sentiment_scorer is not None,
            self.store is not None,
            self.stock_scorer is not None,
            self.llm_analyzer is not None,
            self.pusher is not None,
        )

    # ==================================================================
    # 公开接口
    # ==================================================================

    def run_nightly_pipeline(self) -> Dict:
        """夜间管线：采集 + NLP 分析 + 存储。

        Returns:
            摘要字典 {stocks_scanned, posts_collected, sentiments_stored, errors}
        """
        now = datetime.now(BEIJING_TZ)
        today_str = now.strftime("%Y-%m-%d")
        logger.info("=" * 60)
        logger.info(
            "[夜间管线] 启动 | 北京时间 %s", now.strftime("%Y-%m-%d %H:%M:%S")
        )

        summary: Dict = {
            "pipeline": "nightly",
            "date": today_str,
            "stocks_scanned": 0,
            "posts_collected": 0,
            "sentiments_stored": 0,
            "errors": [],
        }

        # ---- 1. 获取股票池 ----
        stocks = self._get_stock_universe()
        summary["stocks_scanned"] = len(stocks)
        if not stocks:
            msg = "股票池为空，夜间管线终止"
            logger.error("[夜间管线] %s", msg)
            summary["errors"].append(msg)
            return summary

        logger.info("[夜间管线] 股票池: %d 只", len(stocks))

        # ---- 2. 社交媒体采集 ----
        all_posts_by_source: Dict[str, Dict[str, list]] = {}
        if self.source_manager:
            try:
                self.source_manager.check_health()
                all_posts_by_source = self.source_manager.fetch_all_posts(stocks)
                total_posts = sum(
                    len(posts)
                    for src in all_posts_by_source.values()
                    for posts in src.values()
                )
                summary["posts_collected"] = total_posts
                logger.info("[夜间管线] 采集完成: %d 条帖子", total_posts)
            except Exception as exc:
                msg = f"社交媒体采集失败: {exc}"
                logger.error("[夜间管线] %s", msg)
                summary["errors"].append(msg)
        else:
            msg = "SourceManager 不可用，跳过采集"
            logger.warning("[夜间管线] %s", msg)
            summary["errors"].append(msg)

        # ---- 3. SnowNLP 批量分析 + 聚合 ----
        if self.nlp_analyzer and all_posts_by_source:
            sentiments_stored = self._analyze_and_store(
                all_posts_by_source, today_str
            )
            summary["sentiments_stored"] = sentiments_stored
        else:
            if not self.nlp_analyzer:
                summary["errors"].append("SnowNLPAnalyzer 不可用")
            if not all_posts_by_source:
                summary["errors"].append("无帖子数据可供分析")

        # ---- 4. 日志摘要 ----
        logger.info(
            "[夜间管线] 完成 | 扫描=%d, 采集=%d, 存储=%d, 错误=%d",
            summary["stocks_scanned"],
            summary["posts_collected"],
            summary["sentiments_stored"],
            len(summary["errors"]),
        )
        logger.info("=" * 60)

        return summary

    def run_morning_pipeline(self) -> List[StockCandidate]:
        """晨间管线：评分 + LLM 验证 + 推荐 + 通知。

        Returns:
            推荐列表 (List[StockCandidate])
        """
        now = datetime.now(BEIJING_TZ)
        today_str = now.strftime("%Y-%m-%d")
        # 情绪数据可能在昨晚存储
        yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info("=" * 60)
        logger.info(
            "[晨间管线] 启动 | 北京时间 %s", now.strftime("%Y-%m-%d %H:%M:%S")
        )

        recommendations: List[StockCandidate] = []

        # ---- 1. 加载夜间数据 ----
        sentiment_map: Dict[str, StockSentimentAggregate] = {}
        if self.store:
            # 尝试今日，回退到昨日
            for date in (today_str, yesterday_str):
                aggregates = self.store.get_all_sentiments_for_date(
                    date, source="combined"
                )
                if aggregates:
                    sentiment_map = {a.stock_code: a for a in aggregates}
                    logger.info(
                        "[晨间管线] 加载 %s 情绪数据: %d 只股票",
                        date, len(sentiment_map),
                    )
                    break
            if not sentiment_map:
                logger.warning("[晨间管线] 无夜间情绪数据可用")
        else:
            logger.warning("[晨间管线] SentimentStore 不可用")

        # ---- 2. 可选：增量采集隔夜帖子 ----
        if self.source_manager and self.nlp_analyzer and sentiment_map:
            try:
                stocks_to_update = [
                    {"code": code, "name": agg.stock_name}
                    for code, agg in list(sentiment_map.items())[:20]
                ]
                if stocks_to_update:
                    delta_posts = self.source_manager.fetch_all_posts(
                        stocks_to_update
                    )
                    delta_count = sum(
                        len(p)
                        for src in delta_posts.values()
                        for p in src.values()
                    )
                    if delta_count > 0:
                        self._analyze_and_store(delta_posts, today_str)
                        logger.info(
                            "[晨间管线] 增量采集: %d 条帖子", delta_count
                        )
            except Exception as exc:
                logger.warning("[晨间管线] 增量采集失败: %s", exc)

        # ---- 3. 获取行情并评分 ----
        if self.stock_scorer:
            candidates = self._score_all_candidates(sentiment_map)
            logger.info("[晨间管线] 评分完成: %d 只候选", len(candidates))
        else:
            logger.error("[晨间管线] SentimentStockScorer 不可用，无法评分")
            return recommendations

        # ---- 4. LLM 验证 Top-N ----
        if self.llm_analyzer and candidates:
            top_n = NLP_CONFIG.get("llm_top_n", 10)
            top_candidates = sorted(
                candidates, key=lambda c: c.total_score, reverse=True
            )[:top_n]
            for cand in top_candidates:
                try:
                    llm_result = self.llm_analyzer.analyze(cand)
                    if isinstance(llm_result, dict):
                        cand.llm_summary = llm_result.get("summary", "")
                        llm_score = llm_result.get("score")
                        if llm_score is not None:
                            # 将 LLM 分数融入情绪分
                            cand.sentiment_score = (
                                cand.sentiment_score * 0.7 + float(llm_score) * 0.3
                            )
                            # 重算总分
                            cand.total_score = self.stock_scorer.calculate_total_score(
                                cand.technical_score,
                                cand.capital_score,
                                cand.sentiment_score,
                                cand.risk_adjustment,
                            )
                            cand.signal = self.stock_scorer.generate_signal(cand)
                    elif isinstance(llm_result, str):
                        cand.llm_summary = llm_result
                except Exception as exc:
                    logger.warning(
                        "[晨间管线] LLM分析 %s 失败: %s",
                        cand.stock_code, exc,
                    )
        else:
            if not self.llm_analyzer:
                logger.info("[晨间管线] LLM 不可用，跳过验证")

        # ---- 5. 生成推荐 ----
        recommendations = self.stock_scorer.generate_recommendations(candidates)

        # ---- 6. 检查持仓卖出信号 ----
        sell_signals: List[Dict] = []
        if self.store:
            sell_signals = self._check_sell_signals(sentiment_map)

        # ---- 7. 保存推荐记录 ----
        if self.store and recommendations:
            for cand in recommendations:
                if cand.signal in ("STRONG_BUY", "BUY"):
                    rec = DailyRecommendation(
                        date=today_str,
                        stock_code=cand.stock_code,
                        stock_name=cand.stock_name,
                        signal=cand.signal,
                        entry_price=cand.price,
                        total_score=cand.total_score,
                        sentiment_score=cand.sentiment_score,
                    )
                    try:
                        self.store.save_recommendation(rec)
                    except Exception as exc:
                        logger.warning(
                            "[晨间管线] 保存推荐失败 %s: %s",
                            cand.stock_code, exc,
                        )

        # ---- 8. 发送通知 ----
        if recommendations or sell_signals:
            report = self._generate_report(recommendations, sell_signals)
            self._send_notification(report)

        logger.info(
            "[晨间管线] 完成 | 推荐=%d, 卖出信号=%d",
            len(recommendations), len(sell_signals),
        )
        logger.info("=" * 60)

        return recommendations

    def run_full_pipeline(self) -> Dict:
        """便捷方法：依次执行夜间管线 + 晨间管线。

        Returns:
            字典 {'recommendations': [...], 'report': '...', 'sell_signals': [...]}
        """
        logger.info("[全量管线] 开始 =========================")
        nightly_summary = self.run_nightly_pipeline()
        recommendations = self.run_morning_pipeline()

        # 生成卖出信号（从晨间管线的情绪数据重新获取）
        sell_signals: List[Dict] = []
        if self.store:
            now = datetime.now(BEIJING_TZ)
            today_str = now.strftime("%Y-%m-%d")
            yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            sentiment_map: Dict[str, StockSentimentAggregate] = {}
            for date in (today_str, yesterday_str):
                aggregates = self.store.get_all_sentiments_for_date(
                    date, source="combined"
                )
                if aggregates:
                    sentiment_map = {a.stock_code: a for a in aggregates}
                    break
            if sentiment_map:
                sell_signals = self._check_sell_signals(sentiment_map)

        # 始终生成报告（即使推荐和卖出信号都为空）
        report = self._generate_report(recommendations, sell_signals)

        logger.info("[全量管线] 结束 =========================")
        return {
            "recommendations": recommendations,
            "report": report,
            "sell_signals": sell_signals,
        }

    # ==================================================================
    # 内部方法
    # ==================================================================

    def _get_stock_universe(self) -> List[Dict]:
        """获取过滤后的股票池。

        降级策略（按优先级）:
            1. akshare ``stock_zh_a_spot_em()``
            2. 腾讯财经 API (qt.gtimg.cn)
            3. baostock
            4. 默认股票列表

        Returns:
            [{"code": "600519", "name": "贵州茅台"}, ...]
        """
        # --- 1. 尝试 akshare ---
        try:
            import akshare as ak

            logger.info("[StockUniverse] 通过 akshare 获取 A 股行情...")
            df = ak.stock_zh_a_spot_em()

            if df is not None and not df.empty and self.stock_scorer:
                filtered = self.stock_scorer.filter_universe(df)
                if not filtered.empty:
                    stocks = []
                    for _, row in filtered.iterrows():
                        stocks.append({
                            "code": str(row.get("代码", "")),
                            "name": str(row.get("名称", "")),
                        })
                    logger.info(
                        "[StockUniverse] akshare: %d 只股票通过筛选", len(stocks)
                    )
                    return stocks

            logger.warning("[StockUniverse] akshare 返回数据为空或筛选后为空")
        except ImportError:
            logger.info("[StockUniverse] akshare 未安装")
        except Exception as exc:
            logger.warning("[StockUniverse] akshare 调用失败: %s", exc)

        # --- 2. 尝试腾讯财经 API ---
        try:
            from data.tencent_api import get_stock_universe as tencent_universe

            logger.info("[StockUniverse] akshare不可用，尝试腾讯财经 API...")
            df = tencent_universe()

            if df is not None and not df.empty and self.stock_scorer:
                filtered = self.stock_scorer.filter_universe(df)
                if not filtered.empty:
                    stocks = []
                    for _, row in filtered.iterrows():
                        stocks.append({
                            "code": str(row.get("代码", "")),
                            "name": str(row.get("名称", "")),
                        })
                    logger.info(
                        "[StockUniverse] 腾讯API: %d 只股票通过筛选", len(stocks)
                    )
                    return stocks

            logger.warning("[StockUniverse] 腾讯API 返回数据为空或筛选后为空")
        except Exception as exc:
            logger.warning("[StockUniverse] 腾讯API 也失败: %s", exc)

        # --- 3. 尝试 baostock 备选 ---
        try:
            import baostock as bs
            logger.info("[StockUniverse] 尝试 baostock...")
            bs.login()
            rs = bs.query_stock_basic(code_name="", code="")
            stocks_data = []
            while rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                # row: [code, code_name, ipoDate, outDate, type, status]
                if len(row) >= 6 and row[4] == '1' and row[5] == '1':  # type=股票, status=上市
                    code = row[0].replace('sh.', '').replace('sz.', '')
                    name = row[1]
                    # 排除ST
                    if 'ST' not in name and '*ST' not in name:
                        stocks_data.append({"code": code, "name": name})
            bs.logout()
            if stocks_data:
                logger.info("[StockUniverse] baostock: %d 只股票", len(stocks_data))
                return stocks_data[:500]  # 限制数量，避免采集过慢
        except Exception as exc:
            logger.warning("[StockUniverse] baostock 也失败: %s", exc)

        # --- 4. 最终回退 ---
        logger.info(
            "[StockUniverse] 使用默认股票列表 (%d 只)", len(_DEFAULT_STOCKS)
        )
        return list(_DEFAULT_STOCKS)

    def _analyze_and_store(
        self,
        all_posts_by_source: Dict[str, Dict[str, list]],
        date_str: str,
    ) -> int:
        """对采集到的帖子进行 NLP 分析、聚合，并存储到 SQLite。

        Returns:
            成功存储的聚合记录数。
        """
        stored_count = 0

        # 按股票代码聚合所有来源的帖子
        # 结构: {stock_code: {source_name: [posts]}}
        stock_source_posts: Dict[str, Dict[str, list]] = {}
        for source_name, stock_posts in all_posts_by_source.items():
            for stock_code, posts in stock_posts.items():
                if stock_code not in stock_source_posts:
                    stock_source_posts[stock_code] = {}
                stock_source_posts[stock_code][source_name] = posts

                # 保存帖子到数据库
                if self.store and posts:
                    try:
                        self.store.save_posts(posts)
                    except Exception as exc:
                        logger.warning(
                            "保存帖子失败 [%s/%s]: %s",
                            source_name, stock_code, exc,
                        )

        # 逐股票分析
        for stock_code, source_posts_map in stock_source_posts.items():
            try:
                source_aggregates: Dict[str, StockSentimentAggregate] = {}

                for source_name, posts in source_posts_map.items():
                    if not posts:
                        continue

                    stock_name = posts[0].stock_name if posts else stock_code

                    # 获取前一日聚合（用于计算变化量）
                    prev_agg = None
                    if self.store:
                        yesterday = (
                            datetime.strptime(date_str, "%Y-%m-%d")
                            - timedelta(days=1)
                        ).strftime("%Y-%m-%d")
                        prev_agg = self.store.get_sentiment(
                            stock_code, yesterday, source_name
                        )

                    # SnowNLP 分析 + 聚合
                    agg = self.nlp_analyzer.analyze_stock(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        date=date_str,
                        source=source_name,
                        posts=posts,
                        prev_aggregate=prev_agg,
                    )
                    source_aggregates[source_name] = agg

                    # 保存单源聚合
                    if self.store:
                        try:
                            self.store.save_sentiment_aggregate(agg)
                        except Exception as exc:
                            logger.warning(
                                "保存聚合失败 [%s/%s]: %s",
                                source_name, stock_code, exc,
                            )

                # 多源合并
                if source_aggregates and self.sentiment_scorer:
                    combined = self.sentiment_scorer.combine_sources(
                        source_aggregates
                    )
                    combined.score = self.sentiment_scorer.calculate_sentiment_score(
                        combined
                    )

                    if self.store:
                        try:
                            self.store.save_sentiment_aggregate(combined)
                            stored_count += 1
                        except Exception as exc:
                            logger.warning(
                                "保存综合聚合失败 [%s]: %s", stock_code, exc
                            )

            except Exception as exc:
                logger.warning(
                    "分析股票 %s 失败: %s", stock_code, exc
                )

        logger.info("NLP分析+存储完成: %d 只股票", stored_count)
        return stored_count

    def _score_all_candidates(
        self,
        sentiment_map: Dict[str, StockSentimentAggregate],
    ) -> List[StockCandidate]:
        """对股票池中所有股票进行综合评分。

        优先使用 akshare 实时行情数据进行技术面/资金面评分；
        不可用时使用基于情绪数据的简化评分。

        Returns:
            StockCandidate 列表（未排序）。
        """
        candidates: List[StockCandidate] = []

        # 尝试获取实时行情（akshare -> 腾讯API -> 放弃）
        realtime_df = None
        try:
            import akshare as ak
            realtime_df = ak.stock_zh_a_spot_em()
            if realtime_df is not None and not realtime_df.empty:
                realtime_df["代码"] = realtime_df["代码"].astype(str)
                realtime_df = realtime_df.set_index("代码")
                logger.info(
                    "[评分] akshare 获取实时行情: %d 只", len(realtime_df)
                )
        except ImportError:
            logger.info("[评分] akshare 未安装")
        except Exception as exc:
            logger.warning("[评分] akshare 获取实时行情失败: %s", exc)

        # akshare 失败时尝试腾讯 API
        if realtime_df is None or realtime_df.empty:
            try:
                from data.tencent_api import fetch_realtime_quotes
                stock_codes = list(sentiment_map.keys())
                if stock_codes:
                    tencent_df = fetch_realtime_quotes(stock_codes)
                    if tencent_df is not None and not tencent_df.empty:
                        tencent_df["代码"] = tencent_df["代码"].astype(str)
                        realtime_df = tencent_df.set_index("代码")
                        logger.info(
                            "[评分] 腾讯API 获取实时行情: %d 只",
                            len(realtime_df),
                        )
            except Exception as exc:
                logger.warning("[评分] 腾讯API 获取实时行情也失败: %s", exc)

        if realtime_df is None or (hasattr(realtime_df, 'empty') and realtime_df.empty):
            logger.info("[评分] 无实时行情数据，使用简化评分")

        # 评分
        for stock_code, agg in sentiment_map.items():
            try:
                sentiment_score = agg.score
                sentiment_details = {
                    "avg_sentiment": agg.avg_sentiment,
                    "bullish_ratio": agg.bullish_ratio,
                    "disagreement_index": agg.disagreement_index,
                    "comment_volume": agg.comment_volume,
                    "sentiment_change": agg.sentiment_change,
                }

                if realtime_df is not None and stock_code in realtime_df.index:
                    row = realtime_df.loc[stock_code]
                    cand = self.stock_scorer.score_candidate(
                        row=row,
                        sentiment_score=sentiment_score,
                        sentiment_details=sentiment_details,
                    )
                else:
                    # 无实时行情：仅用情绪数据构建简化候选
                    cand = StockCandidate(
                        stock_code=stock_code,
                        stock_name=agg.stock_name,
                        sentiment_score=round(sentiment_score, 2),
                        sentiment_details=sentiment_details,
                        technical_score=50.0,  # 默认中性
                        capital_score=50.0,
                    )
                    cand.risk_adjustment = self.stock_scorer.apply_risk_adjustment(
                        cand
                    )
                    cand.total_score = self.stock_scorer.calculate_total_score(
                        cand.technical_score,
                        cand.capital_score,
                        cand.sentiment_score,
                        cand.risk_adjustment,
                    )
                    cand.signal = self.stock_scorer.generate_signal(cand)

                candidates.append(cand)

            except Exception as exc:
                logger.warning("[评分] 股票 %s 评分失败: %s", stock_code, exc)

        return candidates

    def _check_sell_signals(
        self,
        sentiment_map: Dict[str, StockSentimentAggregate],
    ) -> List[Dict]:
        """检查持仓股的卖出信号。

        卖出条件:
          - 情绪反转（sentiment_change < reversal_threshold）
          - 止损/止盈（需要实时行情）

        Returns:
            卖出信号列表 [{"stock_code", "stock_name", "reason"}, ...]
        """
        sell_signals: List[Dict] = []

        if not self.store:
            return sell_signals

        open_positions = self.store.get_open_positions()
        if not open_positions:
            logger.info("[卖出检查] 无持仓")
            return sell_signals

        reversal_threshold = TRADING_CONFIG.get(
            "sentiment_reversal_threshold", -0.30
        )

        for pos in open_positions:
            reasons: List[str] = []

            # 情绪反转检查
            agg = sentiment_map.get(pos.stock_code)
            if agg and agg.sentiment_change < reversal_threshold:
                reasons.append(
                    f"情绪反转 (变化={agg.sentiment_change:.2f}, "
                    f"阈值={reversal_threshold})"
                )

            if reasons:
                sell_signals.append({
                    "stock_code": pos.stock_code,
                    "stock_name": pos.stock_name,
                    "entry_date": pos.date,
                    "entry_price": pos.entry_price,
                    "reason": "; ".join(reasons),
                })
                logger.info(
                    "[卖出信号] %s(%s): %s",
                    pos.stock_name, pos.stock_code, "; ".join(reasons),
                )

        return sell_signals

    def _generate_report(
        self,
        recommendations: List[StockCandidate],
        sell_signals: List[Dict],
    ) -> str:
        """生成 Markdown 格式的每日报告。"""
        now = datetime.now(BEIJING_TZ)
        lines: List[str] = []

        lines.append(f"# A股情绪选股 | {now.strftime('%m月%d日 %H:%M')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # ---- 买入推荐 ----
        lines.append("## 买入推荐")
        lines.append("")
        if recommendations:
            for i, cand in enumerate(recommendations):
                lines.append(
                    f"{i + 1}. **{cand.stock_name}({cand.stock_code})** "
                    f"| {cand.signal or 'N/A'}"
                )
                # 仅在有实际行情数据时显示价格行
                if cand.price > 0:
                    lines.append(
                        f"   - 现价 {cand.price:.2f} | "
                        f"涨幅 {cand.change_pct:+.2f}% | "
                        f"换手 {cand.turnover_rate:.1f}%"
                    )
                lines.append(
                    f"   - 总分 **{cand.total_score:.1f}** "
                    f"(技术={cand.technical_score:.0f} "
                    f"资金={cand.capital_score:.0f} "
                    f"情绪={cand.sentiment_score:.0f} "
                    f"风险={cand.risk_adjustment:.0f})"
                )
                if cand.suggested_hold_days > 0:
                    lines.append(
                        f"   - 建议持有 {cand.suggested_hold_days} 天 | "
                        f"止损 {cand.stop_loss_pct}% | "
                        f"止盈 {cand.take_profit_pct}%"
                    )
                if cand.reason:
                    lines.append(f"   - {cand.reason}")
                if cand.llm_summary:
                    lines.append(f"   - LLM: {cand.llm_summary}")
                lines.append("")
        else:
            lines.append("今日无符合条件的买入推荐。")
            lines.append("")

        # ---- 卖出信号 ----
        if sell_signals:
            lines.append("---")
            lines.append("")
            lines.append("## 卖出信号")
            lines.append("")
            for sig in sell_signals:
                lines.append(
                    f"- **{sig['stock_name']}({sig['stock_code']})** "
                    f"| 入场日 {sig.get('entry_date', 'N/A')} "
                    f"| 入场价 {sig.get('entry_price', 0):.2f}"
                )
                lines.append(f"  - 原因: {sig['reason']}")
            lines.append("")

        # ---- 免责声明 ----
        lines.append("---")
        lines.append("")
        lines.append(
            "*免责声明：本报告由算法自动生成，仅供参考，不构成投资建议。"
            "投资有风险，入市需谨慎。*"
        )

        return "\n".join(lines)

    def _send_notification(self, report: str) -> None:
        """发送通知报告（飞书 + 邮件，双通道）。"""
        sent_any = False
        today_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")

        # 飞书通知
        if self.pusher and FEISHU_WEBHOOK_URL:
            try:
                success = self.pusher.send_text(report)
                if success:
                    logger.info("[通知] 飞书发送成功")
                    sent_any = True
                else:
                    logger.warning("[通知] 飞书发送失败")
            except Exception as exc:
                logger.warning("[通知] 飞书发送异常: %s", exc)

        # 邮件通知
        try:
            from notification.email_sender import EmailSender
            email = EmailSender()
            if email.available:
                success = email.send_daily_report(report, today_str)
                if success:
                    logger.info("[通知] 邮件发送成功")
                    sent_any = True
                else:
                    logger.warning("[通知] 邮件发送失败")
        except Exception as exc:
            logger.warning("[通知] 邮件模块异常: %s", exc)

        if not sent_any:
            logger.info("[通知] 无可用通知渠道，报告仅打印到日志")
            logger.info("\n%s", report)


# ==================================================================
# CLI 入口
# ==================================================================

def _setup_logging():
    """配置日志格式。"""
    log_fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # 确保 logs 目录存在
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    try:
        from config import LOG_FILE
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(logging.Formatter(log_fmt))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass


if __name__ == "__main__":
    _setup_logging()

    scheduler = SentimentScheduler()

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "nightly":
            scheduler.run_nightly_pipeline()
        elif cmd == "morning":
            scheduler.run_morning_pipeline()
        elif cmd == "full":
            scheduler.run_full_pipeline()
        else:
            print(f"未知命令: {cmd}")
            print("用法: python scheduler.py [nightly|morning|full]")
            sys.exit(1)
    else:
        # 默认执行全量管线
        scheduler.run_full_pipeline()
