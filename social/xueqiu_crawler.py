"""雪球(Xueqiu)社交数据爬虫

雪球是中国最大的投资社交平台之一，大V观点对市场有较大影响力。
本模块通过雪球API获取个股讨论帖子，特别关注作者粉丝数(大V权重)。
"""

import re
import logging
import warnings
from datetime import datetime
from typing import List, Optional

import requests
from urllib3.exceptions import InsecureRequestWarning

from social.base_source import BaseSocialSource
from storage.models import SocialPost

# suppress SSL warnings for proxy environment
warnings.filterwarnings("ignore", category=InsecureRequestWarning)

logger = logging.getLogger(__name__)


class XueqiuCrawler(BaseSocialSource):
    """雪球社交数据源

    特点：
    - 需要先访问首页获取cookie，再调用API
    - 使用 requests.Session 保持cookie
    - 大V粉丝数(author_followers)用于加权
    - 股票代码映射: 6xxxxx -> SH, 0xxxxx/3xxxxx -> SZ
    """

    BASE_URL = "https://xueqiu.com"

    # 股票讨论时间线
    STOCK_TIMELINE_API = (
        "https://xueqiu.com/statuses/stock_timeline.json"
        "?symbol_id={symbol}&count={count}&source=all"
    )

    # 股票搜索讨论
    STOCK_SEARCH_API = (
        "https://xueqiu.com/query/v1/symbol/search/status.json"
        "?q={query}&count={count}&comment=0&symbol={symbol}"
        "&hl=0&source=all&sort=time&page=1"
    )

    def __init__(self, min_interval: float = 3.0, max_retries: int = 3,
                 timeout: int = 15):
        """初始化雪球爬虫

        Args:
            min_interval: 请求最小间隔（雪球较严格，默认3秒）
            max_retries: 最大重试次数
            timeout: 请求超时时间
        """
        super().__init__(
            name="xueqiu",
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
        )
        self.session = requests.Session()
        self._cookie_initialized = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_stock_posts(self, stock_code: str, stock_name: str = "",
                          limit: int = 30) -> List[SocialPost]:
        """获取指定股票在雪球上的讨论帖子

        Args:
            stock_code: 股票代码（纯数字，如 '600519'）
            stock_name: 股票名称（如 '贵州茅台'）
            limit: 最多获取条数
        Returns:
            SocialPost列表
        """
        symbol = self._to_xueqiu_symbol(stock_code)
        if not symbol:
            logger.warning(f"[xueqiu] 无法识别股票代码格式: {stock_code}")
            return []

        self._ensure_cookies()

        posts: List[SocialPost] = []

        # 优先尝试 stock_timeline 接口
        try:
            timeline_posts = self._retry_request(
                self._fetch_timeline, symbol, stock_code, stock_name, limit
            )
            if timeline_posts:
                posts.extend(timeline_posts)
        except Exception as e:
            logger.warning(f"[xueqiu] stock_timeline 接口失败({symbol}): {e}")

        # 如果数量不足且有股票名称，尝试搜索接口补充
        if len(posts) < limit and stock_name:
            remaining = limit - len(posts)
            try:
                search_posts = self._retry_request(
                    self._fetch_search, symbol, stock_code, stock_name, remaining
                )
                if search_posts:
                    # 去重：按 url 去重
                    existing_urls = {p.url for p in posts}
                    for p in search_posts:
                        if p.url not in existing_urls:
                            posts.append(p)
                            existing_urls.add(p.url)
            except Exception as e:
                logger.warning(f"[xueqiu] search 接口失败({symbol}): {e}")

        posts = posts[:limit]
        logger.info(f"[xueqiu] {stock_code} {stock_name} 获取 {len(posts)} 条帖子")
        return posts

    def health_check(self) -> bool:
        """检查雪球数据源是否可用，尝试获取贵州茅台的帖子"""
        try:
            posts = self.fetch_stock_posts("600519", "贵州茅台", limit=5)
            healthy = len(posts) > 0
            if healthy:
                logger.info("[xueqiu] 健康检查通过")
            else:
                logger.warning("[xueqiu] 健康检查: 未获取到帖子")
            return healthy
        except Exception as e:
            logger.error(f"[xueqiu] 健康检查失败: {e}")
            return False

    # ------------------------------------------------------------------
    # Cookie management
    # ------------------------------------------------------------------

    def _ensure_cookies(self):
        """确保session中有有效的cookie

        首次访问雪球首页获取 xq_a_token 等cookie。
        """
        if self._cookie_initialized:
            return

        self._rate_limit()
        try:
            headers = self._build_headers({
                "Accept": "text/html,application/xhtml+xml,application/xml;"
                          "q=0.9,image/webp,*/*;q=0.8",
                "Referer": "https://www.google.com/",
            })
            resp = self.session.get(
                self.BASE_URL,
                headers=headers,
                timeout=self.timeout,
                verify=False,
            )
            resp.raise_for_status()
            self._cookie_initialized = True
            logger.debug("[xueqiu] cookie 初始化成功")
        except Exception as e:
            logger.error(f"[xueqiu] cookie 初始化失败: {e}")
            raise

    # ------------------------------------------------------------------
    # Stock code mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _to_xueqiu_symbol(stock_code: str) -> Optional[str]:
        """将纯数字股票代码转为雪球格式

        规则：
        - 6xxxxx -> SH6xxxxx (上交所)
        - 0xxxxx, 3xxxxx -> SZ0xxxxx / SZ3xxxxx (深交所)

        Args:
            stock_code: 纯数字代码，如 '600519'
        Returns:
            雪球格式代码，如 'SH600519'；无法识别返回 None
        """
        code = stock_code.strip()
        if not re.match(r"^\d{6}$", code):
            return None

        if code.startswith("6"):
            return f"SH{code}"
        elif code.startswith("0") or code.startswith("3"):
            return f"SZ{code}"
        else:
            return None

    # ------------------------------------------------------------------
    # API fetchers
    # ------------------------------------------------------------------

    def _fetch_timeline(self, symbol: str, stock_code: str,
                        stock_name: str, count: int) -> List[SocialPost]:
        """通过 stock_timeline 接口获取帖子"""
        self._rate_limit()

        url = self.STOCK_TIMELINE_API.format(symbol=symbol, count=count)
        headers = self._build_headers({
            "Accept": "application/json, text/plain, */*",
            "Referer": f"https://xueqiu.com/S/{symbol}",
            "X-Requested-With": "XMLHttpRequest",
        })

        resp = self.session.get(
            url, headers=headers, timeout=self.timeout, verify=False
        )
        resp.raise_for_status()
        data = resp.json()

        posts = []
        statuses = data.get("statuses") or data.get("list") or []
        for item in statuses:
            post = self._parse_post(item, stock_code, stock_name)
            if post:
                posts.append(post)

        return posts

    def _fetch_search(self, symbol: str, stock_code: str,
                      stock_name: str, count: int) -> List[SocialPost]:
        """通过搜索接口获取帖子"""
        self._rate_limit()

        url = self.STOCK_SEARCH_API.format(
            query=stock_name, symbol=symbol, count=count
        )
        headers = self._build_headers({
            "Accept": "application/json, text/plain, */*",
            "Referer": f"https://xueqiu.com/S/{symbol}",
            "X-Requested-With": "XMLHttpRequest",
        })

        resp = self.session.get(
            url, headers=headers, timeout=self.timeout, verify=False
        )
        resp.raise_for_status()
        data = resp.json()

        posts = []
        statuses = data.get("statuses") or data.get("list") or []
        for item in statuses:
            post = self._parse_post(item, stock_code, stock_name)
            if post:
                posts.append(post)

        return posts

    # ------------------------------------------------------------------
    # Post parsing
    # ------------------------------------------------------------------

    def _parse_post(self, item: dict, stock_code: str,
                    stock_name: str) -> Optional[SocialPost]:
        """将雪球API返回的单条数据解析为 SocialPost

        Args:
            item: API返回的单条帖子字典
            stock_code: 股票代码
            stock_name: 股票名称
        Returns:
            SocialPost 或 None（解析失败时）
        """
        try:
            # 标题和内容
            title = item.get("title") or item.get("description") or ""
            content = item.get("text") or item.get("description") or ""

            # 清理HTML标签
            title = self._strip_html(title)
            content = self._strip_html(content)

            if not title and not content:
                return None

            # 作者信息
            user_info = item.get("user") or {}
            author = (
                user_info.get("screen_name")
                or user_info.get("name")
                or item.get("user_id", "unknown")
            )
            author_followers = int(user_info.get("followers_count", 0))

            # 发布时间（雪球使用毫秒时间戳）
            created_at = item.get("created_at")
            if isinstance(created_at, (int, float)):
                publish_time = datetime.fromtimestamp(created_at / 1000)
            else:
                publish_time = datetime.now()

            # 帖子URL
            post_id = item.get("id") or item.get("status_id") or ""
            user_id = (
                user_info.get("id")
                or item.get("user_id")
                or ""
            )
            if post_id and user_id:
                url = f"https://xueqiu.com/{user_id}/{post_id}"
            elif post_id:
                url = f"https://xueqiu.com/statuses/{post_id}"
            else:
                url = ""

            # 互动数据
            retweet_count = int(item.get("retweet_count", 0))
            reply_count = int(item.get("reply_count", 0))
            like_count = int(item.get("like_count") or item.get("fav_count", 0))

            return SocialPost(
                source="xueqiu",
                stock_code=stock_code,
                stock_name=stock_name,
                title=title,
                content=content,
                author=str(author),
                publish_time=publish_time,
                url=url,
                read_count=retweet_count,       # 雪球无阅读数，用转发数近似
                comment_count=reply_count,
                like_count=like_count,
                author_followers=author_followers,
            )
        except Exception as e:
            logger.debug(f"[xueqiu] 解析帖子失败: {e}")
            return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_html(text: str) -> str:
        """移除HTML标签，保留纯文本"""
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.strip()
        return clean
