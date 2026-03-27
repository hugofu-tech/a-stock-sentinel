"""雪球(Xueqiu)社交数据采集器

雪球是中国最大的投资社交平台之一，大V观点对市场有较大影响力。

由于雪球使用阿里云WAF防护，直接HTTP请求被JavaScript挑战拦截，
本模块改用以下两种可靠的数据获取方式：

1. akshare的雪球热帖排行接口（stock_hot_tweet_xq / stock_hot_follow_xq）
   - 通过雪球 /service/v5/stock/screener/screen API获取
   - 该API不需要cookie，不受WAF拦截
   - 提供每只股票的讨论热度（帖子数）和关注人数

2. 东方财富个股新闻接口（stock_news_em）作为内容补充
   - 提供个股相关新闻标题和内容摘要
   - 用于NLP情绪分析的文本来源

两种数据组合后生成SocialPost，既有量化热度信号，又有文本用于情绪分析。
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from social.base_source import BaseSocialSource
from storage.models import SocialPost

logger = logging.getLogger(__name__)

# Cache TTL for hot ranking data (refreshed once per batch)
_RANKING_CACHE_TTL = 300  # 5 minutes


class XueqiuCrawler(BaseSocialSource):
    """雪球社交数据源（基于akshare接口）

    特点：
    - 使用akshare获取雪球热帖排行（讨论数、关注数）
    - 使用东方财富新闻API获取个股新闻内容用于NLP
    - 不直接访问xueqiu.com，避免WAF拦截
    - 热度排行数据有缓存，避免重复请求
    """

    def __init__(self, min_interval: float = 1.0, max_retries: int = 3,
                 timeout: int = 15):
        """初始化雪球数据采集器

        Args:
            min_interval: 请求最小间隔（秒）
            max_retries: 最大重试次数
            timeout: 请求超时时间（秒）
        """
        super().__init__(
            name="xueqiu",
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
        )
        # Cache for hot ranking data: {symbol: {tweet: N, follow: N}}
        self._ranking_cache: Dict[str, dict] = {}
        self._ranking_cache_time: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_stock_posts(self, stock_code: str, stock_name: str = "",
                          limit: int = 30) -> List[SocialPost]:
        """获取指定股票在雪球上的讨论数据

        组合两种数据：
        1. 雪球热帖排行中的讨论热度（转为一条汇总SocialPost）
        2. 东方财富个股新闻（每条新闻转为一条SocialPost）

        Args:
            stock_code: 股票代码（纯数字，如 '600519'）
            stock_name: 股票名称（如 '贵州茅台'）
            limit: 最多获取条数
        Returns:
            SocialPost列表
        """
        posts: List[SocialPost] = []

        # 1. 从雪球热帖排行获取讨论热度数据
        ranking_post = self._get_ranking_post(stock_code, stock_name)
        if ranking_post:
            posts.append(ranking_post)

        # 2. 从东方财富获取个股新闻内容（用于NLP情绪分析）
        remaining = limit - len(posts)
        if remaining > 0:
            news_posts = self._fetch_stock_news(
                stock_code, stock_name, remaining
            )
            posts.extend(news_posts)

        posts = posts[:limit]
        logger.info(
            f"[xueqiu] {stock_code} {stock_name} 获取 {len(posts)} 条数据"
        )
        return posts

    def health_check(self) -> bool:
        """检查数据源是否可用

        通过调用akshare雪球热帖排行接口验证连通性。
        """
        try:
            self._refresh_ranking_cache()
            healthy = len(self._ranking_cache) > 0
            if healthy:
                logger.info(
                    f"[xueqiu] 健康检查通过 "
                    f"(排行榜 {len(self._ranking_cache)} 只股票)"
                )
            else:
                logger.warning("[xueqiu] 健康检查: 排行榜数据为空")
            return healthy
        except Exception as e:
            logger.error(f"[xueqiu] 健康检查失败: {e}")
            return False

    # ------------------------------------------------------------------
    # Ranking data via akshare
    # ------------------------------------------------------------------

    def _refresh_ranking_cache(self):
        """刷新雪球热帖排行缓存

        调用 akshare.stock_hot_tweet_xq 和 stock_hot_follow_xq
        获取全市场讨论数和关注数排行。
        """
        import time
        now = time.time()
        if (self._ranking_cache
                and now - self._ranking_cache_time < _RANKING_CACHE_TTL):
            return

        try:
            import akshare as ak

            # 获取讨论排行（最热门）
            tweet_df = ak.stock_hot_tweet_xq(symbol="最热门")
            for _, row in tweet_df.iterrows():
                symbol = row["股票代码"]  # e.g. SH600519
                code = self._from_xueqiu_symbol(symbol)
                if code:
                    self._ranking_cache.setdefault(code, {})
                    self._ranking_cache[code]["tweet"] = int(
                        row.get("关注", 0) or 0
                    )
                    self._ranking_cache[code]["name"] = row.get("股票简称", "")
                    self._ranking_cache[code]["price"] = float(
                        row.get("最新价", 0) or 0
                    )

            # 获取关注排行
            try:
                follow_df = ak.stock_hot_follow_xq(symbol="最热门")
                for _, row in follow_df.iterrows():
                    symbol = row["股票代码"]
                    code = self._from_xueqiu_symbol(symbol)
                    if code:
                        self._ranking_cache.setdefault(code, {})
                        self._ranking_cache[code]["follow"] = int(
                            row.get("关注", 0) or 0
                        )
            except Exception as e:
                logger.debug(f"[xueqiu] 关注排行获取失败(非关键): {e}")

            self._ranking_cache_time = now
            logger.info(
                f"[xueqiu] 排行缓存刷新完成: {len(self._ranking_cache)} 只股票"
            )
        except Exception as e:
            logger.warning(f"[xueqiu] 排行缓存刷新失败: {e}")
            raise

    def _get_ranking_post(self, stock_code: str,
                          stock_name: str) -> Optional[SocialPost]:
        """从排行缓存中获取指定股票的讨论热度，转为SocialPost

        讨论数和关注数转为一条汇总性质的SocialPost，
        其content包含热度数据，可被NLP分析器识别为热度信号。
        """
        try:
            self._refresh_ranking_cache()
        except Exception:
            return None

        info = self._ranking_cache.get(stock_code)
        if not info:
            return None

        tweet_count = info.get("tweet", 0)
        follow_count = info.get("follow", 0)
        cached_name = info.get("name", stock_name)

        # 构造热度描述文本
        content_parts = []
        if tweet_count > 0:
            content_parts.append(f"雪球讨论热度: {tweet_count}条帖子")
        if follow_count > 0:
            content_parts.append(f"雪球关注人数: {follow_count}人")

        if not content_parts:
            return None

        # 热度分级描述（帮助NLP理解）
        if tweet_count > 50000:
            content_parts.append("该股票在雪球上讨论极为活跃，市场关注度非常高")
        elif tweet_count > 10000:
            content_parts.append("该股票在雪球上讨论活跃，市场关注度较高")
        elif tweet_count > 1000:
            content_parts.append("该股票在雪球上有一定讨论量")
        else:
            content_parts.append("该股票在雪球上讨论较少")

        content = "。".join(content_parts) + "。"
        title = f"{cached_name or stock_code} 雪球热度数据"

        return SocialPost(
            source="xueqiu",
            stock_code=stock_code,
            stock_name=stock_name or cached_name,
            title=title,
            content=content,
            author="雪球热帖排行",
            publish_time=datetime.now(),
            url=f"https://xueqiu.com/S/{self._to_xueqiu_symbol(stock_code) or stock_code}",
            read_count=tweet_count,
            comment_count=0,
            like_count=follow_count,
            author_followers=0,
        )

    # ------------------------------------------------------------------
    # Stock news via akshare (content for NLP)
    # ------------------------------------------------------------------

    def _fetch_stock_news(self, stock_code: str, stock_name: str,
                          limit: int) -> List[SocialPost]:
        """通过akshare获取东方财富个股新闻

        这些新闻提供有实际内容的文本，可用于NLP情绪分析。
        标记source为"xueqiu"以匹配数据源权重配置。

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            limit: 最多获取条数
        Returns:
            SocialPost列表
        """
        posts: List[SocialPost] = []

        try:
            import akshare as ak
            news_df = ak.stock_news_em(symbol=stock_code)

            if news_df is None or news_df.empty:
                return posts

            for _, row in news_df.head(limit).iterrows():
                title = str(row.get("新闻标题", "")).strip()
                content = str(row.get("新闻内容", "")).strip()
                url = str(row.get("新闻链接", "")).strip()
                source_name = str(row.get("文章来源", "")).strip()

                if not title:
                    continue

                # Parse publish time
                raw_time = row.get("发布时间", "")
                publish_time = self._parse_time(raw_time)

                posts.append(SocialPost(
                    source="xueqiu",
                    stock_code=stock_code,
                    stock_name=stock_name,
                    title=title,
                    content=content,
                    author=source_name or "东方财富资讯",
                    publish_time=publish_time,
                    url=url,
                    read_count=0,
                    comment_count=0,
                    like_count=0,
                ))

        except Exception as e:
            logger.warning(f"[xueqiu] 获取个股新闻失败({stock_code}): {e}")

        return posts

    # ------------------------------------------------------------------
    # Stock code mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _to_xueqiu_symbol(stock_code: str) -> Optional[str]:
        """将纯数字股票代码转为雪球格式

        规则：
        - 6xxxxx -> SH6xxxxx (上交所)
        - 0xxxxx, 3xxxxx -> SZ0xxxxx / SZ3xxxxx (深交所)
        """
        code = stock_code.strip()
        if not re.match(r"^\d{6}$", code):
            return None
        if code.startswith("6"):
            return f"SH{code}"
        elif code.startswith("0") or code.startswith("3"):
            return f"SZ{code}"
        return None

    @staticmethod
    def _from_xueqiu_symbol(symbol: str) -> Optional[str]:
        """将雪球格式代码转为纯数字

        SH600519 -> 600519, SZ000001 -> 000001
        """
        if not symbol:
            return None
        symbol = symbol.strip().upper()
        if symbol.startswith("SH") or symbol.startswith("SZ"):
            code = symbol[2:]
            if re.match(r"^\d{6}$", code):
                return code
        return None

    @staticmethod
    def _parse_time(raw_time) -> datetime:
        """解析时间字符串"""
        if not raw_time:
            return datetime.now()
        if isinstance(raw_time, datetime):
            return raw_time
        try:
            raw_str = str(raw_time).strip()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    return datetime.strptime(raw_str, fmt)
                except ValueError:
                    continue
        except Exception:
            pass
        return datetime.now()

    def close(self):
        """兼容旧接口"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
