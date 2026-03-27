"""微博股票讨论数据采集器

原实现通过m.weibo.cn移动端API直接爬取微博帖子，但由于：
- Sina Visitor Cookie系统需要JavaScript执行（服务器端无法完成）
- m.weibo.cn返回432反爬错误

本模块改用以下可靠的数据获取方式：

1. akshare的金十数据微博舆情报告（stock_js_weibo_report）
   - 来源：datacenter-api.jin10.com/weibo/list
   - 提供50只热门股票的微博舆情评分（rate）
   - 支持多个时间维度：2小时/6小时/12小时/1天/1周/1月

2. akshare的东方财富个股新闻（stock_news_em）
   - 提供个股相关新闻标题和内容
   - 作为NLP情绪分析的文本来源

舆情评分（rate）是预计算的情绪指标，正值看多、负值看空。
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from social.base_source import BaseSocialSource
from storage.models import SocialPost

logger = logging.getLogger(__name__)

# Cache TTL for weibo sentiment data
_SENTIMENT_CACHE_TTL = 600  # 10 minutes

# 用于去除HTML标签的正则
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class WeiboStock(BaseSocialSource):
    """微博股票讨论数据源（基于akshare金十数据接口）

    采集策略：
    1. 从金十数据获取微博舆情报告（50只热门股票的情绪评分）
    2. 从东方财富获取个股新闻作为文本内容补充
    3. 将舆情评分转为SocialPost格式供评分引擎使用
    """

    # 金十微博舆情时间维度
    TIME_PERIODS = {
        "2小时": "CNHOUR2",
        "6小时": "CNHOUR6",
        "12小时": "CNHOUR12",
        "1天": "CNHOUR24",
        "1周": "CNDAY7",
        "1月": "CNDAY30",
    }

    def __init__(self, min_interval: float = 1.0, max_retries: int = 3,
                 timeout: int = 15):
        """初始化微博数据采集器

        Args:
            min_interval: 请求最小间隔（秒）
            max_retries: 最大重试次数
            timeout: 请求超时时间（秒）
        """
        super().__init__(
            name="weibo",
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
        )
        # Cache: {stock_name: {period: rate}}
        self._sentiment_cache: Dict[str, Dict[str, float]] = {}
        self._sentiment_cache_time: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_stock_posts(self, stock_code: str, stock_name: str = "",
                          limit: int = 30) -> List[SocialPost]:
        """获取指定股票的微博舆情数据

        Args:
            stock_code: 股票代码（纯数字，如 '600519'）
            stock_name: 股票名称（如 '贵州茅台'）
            limit: 最多获取条数
        Returns:
            帖子列表
        """
        posts: List[SocialPost] = []

        # 1. 从微博舆情报告获取情绪评分
        sentiment_post = self._get_sentiment_post(stock_code, stock_name)
        if sentiment_post:
            posts.append(sentiment_post)

        # 2. 从东方财富获取个股新闻作为补充内容
        remaining = limit - len(posts)
        if remaining > 0 and stock_code:
            news_posts = self._fetch_stock_news(
                stock_code, stock_name, remaining
            )
            posts.extend(news_posts)

        logger.info(
            f"[weibo] 获取 {stock_code} {stock_name} 数据 {len(posts)} 条"
        )
        return posts[:limit]

    def health_check(self) -> bool:
        """检查微博舆情数据是否可用

        通过调用金十数据微博舆情接口验证连通性。
        """
        try:
            self._refresh_sentiment_cache()
            healthy = len(self._sentiment_cache) > 0
            if healthy:
                logger.info(
                    f"[weibo] 健康检查通过 "
                    f"(舆情数据 {len(self._sentiment_cache)} 只股票)"
                )
            else:
                logger.warning("[weibo] 健康检查: 舆情数据为空")
            return healthy
        except Exception as e:
            logger.error(f"[weibo] 健康检查失败: {e}")
            return False

    # ------------------------------------------------------------------
    # Weibo sentiment via akshare (Jin10 Data)
    # ------------------------------------------------------------------

    def _refresh_sentiment_cache(self):
        """刷新微博舆情缓存

        从金十数据获取多个时间维度的微博舆情报告。
        """
        import time
        now = time.time()
        if (self._sentiment_cache
                and now - self._sentiment_cache_time < _SENTIMENT_CACHE_TTL):
            return

        try:
            import akshare as ak

            # 获取多个时间维度的数据
            for label, period_code in [
                ("12小时", "CNHOUR12"),
                ("1天", "CNHOUR24"),
                ("1周", "CNDAY7"),
            ]:
                try:
                    df = ak.stock_js_weibo_report(time_period=period_code)
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            name = str(row.get("name", "")).strip()
                            rate = float(row.get("rate", 0))
                            if name:
                                self._sentiment_cache.setdefault(name, {})
                                self._sentiment_cache[name][label] = rate
                except Exception as e:
                    logger.debug(
                        f"[weibo] 舆情数据获取失败({label}): {e}"
                    )

            self._sentiment_cache_time = now
            logger.info(
                f"[weibo] 舆情缓存刷新完成: {len(self._sentiment_cache)} 只股票"
            )
        except Exception as e:
            logger.warning(f"[weibo] 舆情缓存刷新失败: {e}")
            raise

    def _get_sentiment_post(self, stock_code: str,
                            stock_name: str) -> Optional[SocialPost]:
        """从舆情缓存中获取指定股票的情绪评分

        将微博舆情评分转为SocialPost。
        rate > 0 表示正面情绪（看多），rate < 0 表示负面情绪（看空）。
        """
        try:
            self._refresh_sentiment_cache()
        except Exception:
            return None

        if not stock_name:
            return None

        info = self._sentiment_cache.get(stock_name)
        if not info:
            return None

        # 构造舆情描述文本
        content_parts = [f"微博舆情报告 - {stock_name}({stock_code}):"]

        overall_sentiment = 0.0
        count = 0
        for period, rate in sorted(info.items()):
            if rate > 0:
                sentiment_text = "正面(看多)"
            elif rate < 0:
                sentiment_text = "负面(看空)"
            else:
                sentiment_text = "中性"
            content_parts.append(
                f"  {period}内舆情评分: {rate:+.2f} ({sentiment_text})"
            )
            overall_sentiment += rate
            count += 1

        if count > 0:
            avg = overall_sentiment / count
            if avg > 1.0:
                content_parts.append(
                    f"微博综合舆情强烈看多，市场情绪积极"
                )
            elif avg > 0:
                content_parts.append(f"微博综合舆情偏正面")
            elif avg < -1.0:
                content_parts.append(
                    f"微博综合舆情强烈看空，市场情绪悲观"
                )
            elif avg < 0:
                content_parts.append(f"微博综合舆情偏负面")
            else:
                content_parts.append(f"微博综合舆情中性")

        content = "\n".join(content_parts)
        title = f"{stock_name} 微博舆情评分"

        # Use the 12h rate as the primary signal if available
        primary_rate = info.get("12小时", info.get("1天", 0))

        return SocialPost(
            source="weibo",
            stock_code=stock_code,
            stock_name=stock_name,
            title=title,
            content=content,
            author="金十数据-微博舆情",
            publish_time=datetime.now(),
            url="https://datacenter.jin10.com/market",
            read_count=0,
            comment_count=0,
            like_count=abs(int(primary_rate * 100)),  # rate magnitude as proxy
            author_followers=0,
        )

    # ------------------------------------------------------------------
    # Stock news via akshare (content for NLP)
    # ------------------------------------------------------------------

    def _fetch_stock_news(self, stock_code: str, stock_name: str,
                          limit: int) -> List[SocialPost]:
        """通过akshare获取东方财富个股新闻

        作为微博数据的补充文本来源。
        标记source为"weibo"以匹配数据源权重配置。
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
                    source="weibo",
                    stock_code=stock_code,
                    stock_name=stock_name,
                    title=title,
                    content=content,
                    author=source_name or "财经新闻",
                    publish_time=publish_time,
                    url=url,
                    read_count=0,
                    comment_count=0,
                    like_count=0,
                ))

        except Exception as e:
            logger.warning(f"[weibo] 获取个股新闻失败({stock_code}): {e}")

        return posts

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

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

    @staticmethod
    def _strip_html(text: str) -> str:
        """去除HTML标签"""
        if not text:
            return ""
        return _HTML_TAG_RE.sub("", text)

    @staticmethod
    def _safe_int(value) -> int:
        """安全地将值转换为整数"""
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        if not isinstance(value, str):
            return 0
        value = value.strip()
        if not value or value == "-":
            return 0
        multiplier = 1
        if value.endswith("万"):
            multiplier = 10000
            value = value[:-1]
        elif value.endswith("亿"):
            multiplier = 100000000
            value = value[:-1]
        try:
            return int(float(value) * multiplier)
        except (ValueError, OverflowError):
            return 0

    def close(self):
        """兼容旧接口"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
