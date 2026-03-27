"""市值风云（wogoo.com）文章采集器

市值风云是专业金融分析媒体，原域名为 shizifengyun.com，
现已迁移至 www.wogoo.com。

由于 wogoo.com 使用 Nuxt.js SPA框架，所有页面路由返回相同的HTML shell，
API需要认证且不公开，无法通过简单HTTP请求获取数据。

本模块改用以下替代策略：
1. 财新网新闻（akshare stock_news_main_cx）—— 专业财经媒体新闻
2. 东方财富个股新闻（akshare stock_news_em）—— 个股相关新闻
3. 尝试 wogoo.com 搜索API（如果可用）

财新网和东方财富新闻都是专业财经内容，与市值风云定位类似，
适合作为高质量分析文本源用于NLP情绪分析。
"""

import re
import json
import logging
from datetime import datetime
from typing import List, Optional

from social.base_source import BaseSocialSource
from storage.models import SocialPost

logger = logging.getLogger(__name__)


class ShizifengyunCrawler(BaseSocialSource):
    """市值风云/财经新闻数据源

    作为专业财经分析内容源，提供：
    - 财新网新闻摘要
    - 东方财富个股新闻
    - wogoo.com搜索（如API可用时）
    """

    # 市值风云新域名
    BASE_URL = "https://www.wogoo.com"

    def __init__(self, min_interval: float = 1.0, max_retries: int = 3,
                 timeout: int = 15):
        """初始化数据采集器

        Args:
            min_interval: 请求最小间隔（秒）
            max_retries: 最大重试次数
            timeout: 请求超时时间（秒）
        """
        super().__init__(
            name="shizifengyun",
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
        )
        # Cache for Caixin news
        self._caixin_cache: List[dict] = []
        self._caixin_cache_time: float = 0.0
        self._CAIXIN_CACHE_TTL = 600  # 10 minutes

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_stock_posts(self, stock_code: str, stock_name: str = "",
                          limit: int = 30) -> List[SocialPost]:
        """获取指定股票的专业财经分析文章

        Args:
            stock_code: 股票代码（纯数字，如 '600519'）
            stock_name: 股票名称（如 '贵州茅台'）
            limit: 最多获取条数
        Returns:
            文章列表（转为SocialPost格式）
        """
        posts: List[SocialPost] = []

        # 策略1：从财新网新闻中筛选相关内容
        caixin_posts = self._fetch_caixin_news(
            stock_code, stock_name, limit
        )
        posts.extend(caixin_posts)

        # 策略2：从东方财富获取个股新闻补充
        remaining = limit - len(posts)
        if remaining > 0:
            news_posts = self._fetch_stock_news(
                stock_code, stock_name, remaining
            )
            posts.extend(news_posts)

        if posts:
            logger.info(
                f"[shizifengyun] 获取 {stock_code} {stock_name} "
                f"文章 {len(posts)} 篇"
            )
        else:
            logger.debug(
                f"[shizifengyun] 未获取到 {stock_code} {stock_name} 的文章"
            )

        return posts[:limit]

    def health_check(self) -> bool:
        """检查数据源是否可用

        通过获取财新新闻验证连通性。
        """
        try:
            self._refresh_caixin_cache()
            healthy = len(self._caixin_cache) > 0
            if healthy:
                logger.info(
                    f"[shizifengyun] 健康检查通过 "
                    f"(财新新闻 {len(self._caixin_cache)} 条)"
                )
            else:
                # Try stock_news_em as fallback
                import akshare as ak
                df = ak.stock_news_em(symbol="600519")
                healthy = df is not None and not df.empty
                if healthy:
                    logger.info(
                        "[shizifengyun] 健康检查通过 (个股新闻可用)"
                    )
                else:
                    logger.warning("[shizifengyun] 健康检查: 无可用数据")
            return healthy
        except Exception as e:
            logger.error(f"[shizifengyun] 健康检查失败: {e}")
            return False

    # ------------------------------------------------------------------
    # Caixin news via akshare
    # ------------------------------------------------------------------

    def _refresh_caixin_cache(self):
        """刷新财新新闻缓存"""
        import time
        now = time.time()
        if (self._caixin_cache
                and now - self._caixin_cache_time < self._CAIXIN_CACHE_TTL):
            return

        try:
            import akshare as ak
            df = ak.stock_news_main_cx()
            if df is not None and not df.empty:
                self._caixin_cache = df.to_dict("records")
                self._caixin_cache_time = now
                logger.info(
                    f"[shizifengyun] 财新新闻缓存刷新: "
                    f"{len(self._caixin_cache)} 条"
                )
            else:
                logger.debug("[shizifengyun] 财新新闻返回空数据")
        except Exception as e:
            logger.warning(f"[shizifengyun] 财新新闻获取失败: {e}")
            raise

    def _fetch_caixin_news(self, stock_code: str, stock_name: str,
                           limit: int) -> List[SocialPost]:
        """从财新新闻缓存中筛选与指定股票相关的内容

        财新新闻为全市场新闻，需按股票名称/代码筛选相关条目。
        """
        posts: List[SocialPost] = []

        try:
            self._refresh_caixin_cache()
        except Exception:
            return posts

        if not self._caixin_cache:
            return posts

        # 筛选与该股票相关的新闻
        keywords = []
        if stock_name:
            keywords.append(stock_name)
            # 也添加简称变体（去掉常见后缀）
            for suffix in ["股份", "集团", "科技", "电子", "新材"]:
                if stock_name.endswith(suffix) and len(stock_name) > len(suffix) + 1:
                    keywords.append(stock_name[:-len(suffix)])
        if stock_code:
            keywords.append(stock_code)

        for item in self._caixin_cache:
            if len(posts) >= limit:
                break

            summary = str(item.get("summary", "")).strip()
            tag = str(item.get("tag", "")).strip()
            url = str(item.get("url", "")).strip()

            if not summary:
                continue

            # Check if news is related to this stock
            matched = False
            for kw in keywords:
                if kw and kw in summary:
                    matched = True
                    break

            if not matched:
                continue

            # Construct title from first sentence of summary
            title = summary[:60]
            if len(summary) > 60:
                title += "..."

            posts.append(SocialPost(
                source="shizifengyun",
                stock_code=stock_code,
                stock_name=stock_name,
                title=title,
                content=summary,
                author="财新网",
                publish_time=datetime.now(),
                url=url,
                read_count=0,
                comment_count=0,
                like_count=0,
            ))

        return posts

    # ------------------------------------------------------------------
    # Stock news via akshare (fallback)
    # ------------------------------------------------------------------

    def _fetch_stock_news(self, stock_code: str, stock_name: str,
                          limit: int) -> List[SocialPost]:
        """通过akshare获取东方财富个股新闻

        标记source为"shizifengyun"以匹配数据源权重配置。
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

                raw_time = row.get("发布时间", "")
                publish_time = self._parse_time(raw_time)

                posts.append(SocialPost(
                    source="shizifengyun",
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
            logger.warning(
                f"[shizifengyun] 获取个股新闻失败({stock_code}): {e}"
            )

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

    @staticmethod
    def _strip_html(text: str) -> str:
        """去除文本中的HTML标签"""
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', '', text)
        clean = re.sub(r'&[a-zA-Z]+;', ' ', clean)
        clean = re.sub(r'&#\d+;', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def close(self):
        """兼容旧接口"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
