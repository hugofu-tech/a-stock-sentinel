"""微博股票讨论数据采集器

从微博（m.weibo.cn）移动端API抓取股票相关帖子，
用于社交情绪分析。微博数据噪声较大，内置多层过滤机制。
"""

import re
import time
import json
import base64
import logging
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Optional

import requests
import urllib3

from social.base_source import BaseSocialSource
from storage.models import SocialPost

# 禁用 InsecureRequestWarning（verify=False 场景）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Visitor cookie lifetime (20 min; Sina visitor cookies last ~30 min)
_VISITOR_COOKIE_TTL = 20 * 60

# 用于去除HTML标签的正则
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# 广告关键词
_AD_KEYWORDS = ("广告", "推广", "客服")


class WeiboStock(BaseSocialSource):
    """微博股票讨论数据源

    采集策略：
    1. 使用移动端搜索API（限制较少）
    2. 按股票名称搜索，配合cashtag格式过滤
    3. 多层噪声过滤（互动量、内容长度、相关性、广告）
    """

    # 移动端搜索API
    SEARCH_URL = "https://m.weibo.cn/api/container/getIndex"

    # 备用搜索类型（type=61 为实时搜索）
    SEARCH_TYPE_DEFAULT = "1"
    SEARCH_TYPE_REALTIME = "61"

    # 微博帖子URL模板
    POST_URL_TEMPLATE = "https://m.weibo.cn/detail/{mid}"

    # 内容长度过滤范围
    MIN_CONTENT_LENGTH = 10
    MAX_CONTENT_LENGTH = 500

    def __init__(self, min_interval: float = 2.0, max_retries: int = 3,
                 timeout: int = 15):
        """初始化微博采集器

        Args:
            min_interval: 请求最小间隔（秒），默认2秒
            max_retries: 最大重试次数
            timeout: 请求超时时间（秒）
        """
        super().__init__(
            name="weibo",
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
        )
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update(self._build_headers({
            "Referer": "https://m.weibo.cn/",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        }))
        self._visitor_cookie_initialized = False
        self._visitor_cookie_time: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Sina Visitor Cookie System
    # ------------------------------------------------------------------

    def _init_visitor_cookie(self):
        """通过新浪访客系统获取有效cookie

        Sina visitor system flow:
        1. POST to passport.weibo.com/visitor/genvisitor with platform info
           -> returns a tid (visitor ticket ID) in a JSONP callback
        2. GET passport.weibo.com/visitor/visitor with sub=tid&s=...
           -> sets SUB/SUBP cookies that grant API access

        This is needed on Tencent Cloud (or any server without browser JS)
        because m.weibo.cn APIs return empty data without valid cookies.
        """
        now = time.time()
        cookie_expired = (
            now - self._visitor_cookie_time > _VISITOR_COOKIE_TTL
        )
        if self._visitor_cookie_initialized and not cookie_expired:
            return

        if cookie_expired and self._visitor_cookie_initialized:
            logger.info("[weibo] 访客cookie已过期，正在刷新...")
            self.session.cookies.clear()

        try:
            # Step 1: Generate visitor ticket (tid)
            gen_url = "https://passport.weibo.com/visitor/genvisitor"
            gen_data = {
                "cb": "gen_callback",
                "fp": '{"os":"1","browser":"Chrome120,0,0,0","fonts":"undefined",'
                      '"screenInfo":"1920*1080*24","plugins":""}',
            }
            gen_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://passport.weibo.com/visitor/visitor",
                "User-Agent": self._get_random_ua(),
            }

            self._rate_limit()
            resp = self.session.post(
                gen_url,
                data=gen_data,
                headers=gen_headers,
                timeout=self.timeout,
                verify=False,
            )
            resp.raise_for_status()

            # Response is JSONP: gen_callback({...})
            text = resp.text
            json_match = re.search(r'gen_callback\((.*)\)', text, re.DOTALL)
            if not json_match:
                # Try parsing as plain JSON
                try:
                    gen_data_resp = json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    logger.warning(
                        "[weibo] genvisitor 返回格式异常，跳过访客初始化"
                    )
                    self._visitor_cookie_initialized = True
                    self._visitor_cookie_time = now
                    return
            else:
                gen_data_resp = json.loads(json_match.group(1))

            tid = gen_data_resp.get("data", {}).get("tid", "")
            new_tid = gen_data_resp.get("data", {}).get("new_tid", True)

            if not tid:
                logger.warning("[weibo] genvisitor 未返回tid，跳过访客初始化")
                self._visitor_cookie_initialized = True
                self._visitor_cookie_time = now
                return

            # Step 2: Exchange tid for SUB/SUBP cookies
            visitor_url = "https://passport.weibo.com/visitor/visitor"
            visitor_params = {
                "a": "incarnate",
                "t": tid,
                "w": 2 if new_tid else 3,
                "c": "095",
                "gc": "",
                "cb": "cross_domain",
                "from": "weibo",
                "_rand": time.time(),
            }
            visitor_headers = {
                "Referer": "https://passport.weibo.com/visitor/visitor",
                "User-Agent": self._get_random_ua(),
            }

            self._rate_limit()
            resp2 = self.session.get(
                visitor_url,
                params=visitor_params,
                headers=visitor_headers,
                timeout=self.timeout,
                verify=False,
            )
            resp2.raise_for_status()

            # Response is JSONP: cross_domain({...})
            text2 = resp2.text
            json_match2 = re.search(
                r'cross_domain\((.*)\)', text2, re.DOTALL
            )
            if json_match2:
                visitor_data = json.loads(json_match2.group(1))
                sub = visitor_data.get("data", {}).get("sub", "")
                subp = visitor_data.get("data", {}).get("subp", "")
                if sub:
                    self.session.cookies.set("SUB", sub, domain=".weibo.com")
                if subp:
                    self.session.cookies.set("SUBP", subp, domain=".weibo.com")
                logger.debug(
                    f"[weibo] 访客cookie设置成功: SUB={bool(sub)}, SUBP={bool(subp)}"
                )

            self._visitor_cookie_initialized = True
            self._visitor_cookie_time = now
            logger.info("[weibo] 访客cookie初始化完成")

        except Exception as e:
            logger.warning(f"[weibo] 访客cookie初始化失败: {e}，将尝试无cookie访问")
            # Mark as initialized to avoid retrying every call
            self._visitor_cookie_initialized = True
            self._visitor_cookie_time = now

    def fetch_stock_posts(self, stock_code: str, stock_name: str = "",
                          limit: int = 30) -> List[SocialPost]:
        """获取指定股票的微博帖子

        Args:
            stock_code: 股票代码（纯数字，如 '600519'）
            stock_name: 股票名称（如 '贵州茅台'）
            limit: 最多获取条数
        Returns:
            帖子列表
        """
        # Ensure we have valid visitor cookies before making API calls
        self._init_visitor_cookie()

        # 微博搜索以名称为主；如果没有名称，用股票代码
        query = stock_name if stock_name else stock_code
        posts: List[SocialPost] = []

        # 优先使用默认搜索类型
        try:
            posts = self._retry_request(
                self._fetch_search, query, stock_code, stock_name,
                limit, self.SEARCH_TYPE_DEFAULT,
            )
        except Exception as e:
            logger.warning(
                f"[weibo] 默认搜索获取 {stock_code} 失败: {e}，尝试实时搜索"
            )

        # 如果默认搜索结果不足，补充实时搜索
        if len(posts) < limit:
            try:
                extra = self._retry_request(
                    self._fetch_search, query, stock_code, stock_name,
                    limit - len(posts), self.SEARCH_TYPE_REALTIME,
                )
                # 去重（按mid）
                existing_urls = {p.url for p in posts}
                for p in extra:
                    if p.url not in existing_urls:
                        posts.append(p)
                        existing_urls.add(p.url)
            except Exception as e:
                logger.warning(f"[weibo] 实时搜索获取 {stock_code} 也失败: {e}")

        logger.info(
            f"[weibo] 获取 {stock_code} {stock_name} 帖子 {len(posts)} 条"
        )
        return posts[:limit]

    def health_check(self) -> bool:
        """检查微博搜索API是否可用

        用"贵州茅台"做探活测试。
        """
        try:
            posts = self.fetch_stock_posts("600519", "贵州茅台", limit=5)
            ok = len(posts) > 0
            if ok:
                logger.info("[weibo] 健康检查通过")
            else:
                logger.warning("[weibo] 健康检查失败：未获取到帖子")
            return ok
        except Exception as e:
            logger.error(f"[weibo] 健康检查异常: {e}")
            return False

    # ------------------------------------------------------------------
    # Private: search-based fetching
    # ------------------------------------------------------------------

    def _fetch_search(self, query: str, stock_code: str, stock_name: str,
                      limit: int, search_type: str) -> List[SocialPost]:
        """通过微博移动端搜索API获取帖子

        Args:
            query: 搜索关键词
            stock_code: 股票代码
            stock_name: 股票名称
            limit: 最多获取条数
            search_type: 搜索类型（1=综合, 61=实时）
        Returns:
            过滤后的帖子列表
        """
        posts: List[SocialPost] = []
        max_pages = max(1, (limit + 9) // 10)  # 每页约10条
        max_pages = min(max_pages, 5)  # 最多5页，避免过多请求

        for page in range(1, max_pages + 1):
            if len(posts) >= limit:
                break

            self._rate_limit()
            self.session.headers["User-Agent"] = self._get_random_ua()

            containerid = (
                f"100103type%3D{search_type}%26q%3D"
                f"{urllib.parse.quote(query)}"
            )

            params = {
                "containerid": containerid,
                "page_type": "searchall",
                "page": page,
            }

            resp = self.session.get(
                self.SEARCH_URL,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()

            data = resp.json()
            page_posts = self._parse_search_response(
                data, stock_code, stock_name
            )
            posts.extend(page_posts)

            # 如果本页没有结果，停止翻页
            if not page_posts:
                break

        return posts[:limit]

    def _parse_search_response(self, data: dict, stock_code: str,
                               stock_name: str) -> List[SocialPost]:
        """解析微博搜索API返回的JSON数据"""
        posts: List[SocialPost] = []

        if not isinstance(data, dict) or data.get("ok") != 1:
            logger.debug(f"[weibo] API返回异常: ok={data.get('ok') if isinstance(data, dict) else 'N/A'}")
            return posts

        # 搜索结果在 data -> cards 中
        cards = data.get("data", {}).get("cards", [])
        if not cards:
            return posts

        for card in cards:
            # card_type=9 是微博帖子，card_type=11 是card_group容器
            if card.get("card_type") == 9:
                mblog = card.get("mblog")
                if mblog:
                    post = self._parse_mblog(mblog, stock_code, stock_name)
                    if post:
                        posts.append(post)
            elif card.get("card_type") == 11:
                # card_group 内部可能嵌套多条微博
                for sub_card in card.get("card_group", []):
                    if sub_card.get("card_type") == 9:
                        mblog = sub_card.get("mblog")
                        if mblog:
                            post = self._parse_mblog(
                                mblog, stock_code, stock_name
                            )
                            if post:
                                posts.append(post)

        return posts

    def _parse_mblog(self, mblog: dict, stock_code: str,
                     stock_name: str) -> Optional[SocialPost]:
        """解析单条微博数据，并进行噪声过滤

        Args:
            mblog: 微博JSON对象
            stock_code: 股票代码
            stock_name: 股票名称
        Returns:
            SocialPost 或 None（被过滤掉）
        """
        # 提取原始文本并去除HTML标签
        raw_text = mblog.get("text", "")
        text = self._strip_html(raw_text).strip()

        if not text:
            return None

        # --- 噪声过滤 ---

        # 1. 内容长度过滤
        if len(text) < self.MIN_CONTENT_LENGTH:
            return None
        if len(text) > self.MAX_CONTENT_LENGTH:
            return None

        # 2. 相关性过滤：必须包含股票名称或代码
        if stock_name and stock_name not in text and stock_code not in text:
            return None
        if not stock_name and stock_code not in text:
            return None

        # 3. 广告过滤
        for kw in _AD_KEYWORDS:
            if kw in text:
                return None

        # 4. 最低互动量过滤（至少1条评论或1个赞）
        comments_count = self._safe_int(mblog.get("comments_count", 0))
        attitudes_count = self._safe_int(mblog.get("attitudes_count", 0))
        if comments_count < 1 and attitudes_count < 1:
            return None

        # --- 解析字段 ---

        # 作者
        user_info = mblog.get("user", {}) or {}
        author = user_info.get("screen_name", "匿名")
        author_followers = self._safe_int(
            user_info.get("followers_count", 0)
        )

        # 发布时间
        created_at = mblog.get("created_at", "")
        publish_time = self._parse_weibo_time(created_at)

        # 帖子URL
        mid = str(mblog.get("mid", "") or mblog.get("id", ""))
        url = self.POST_URL_TEMPLATE.format(mid=mid) if mid else ""

        # 互动数据
        reposts_count = self._safe_int(mblog.get("reposts_count", 0))

        # 微博没有独立标题，用文本截断作为标题
        title = text[:50] + "..." if len(text) > 50 else text

        return SocialPost(
            source="weibo",
            stock_code=stock_code,
            stock_name=stock_name,
            title=title,
            content=text,
            author=str(author),
            publish_time=publish_time,
            url=url,
            read_count=reposts_count,  # 微博无阅读数，用转发数代替
            comment_count=comments_count,
            like_count=attitudes_count,
            author_followers=author_followers,
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_html(text: str) -> str:
        """去除HTML标签

        微博内容可能包含 <a href=...>、<span>、<br/> 等HTML标签。
        """
        if not text:
            return ""
        return _HTML_TAG_RE.sub("", text)

    @staticmethod
    def _parse_weibo_time(time_str: str) -> datetime:
        """解析微博的各种时间格式

        支持格式：
        - "刚刚"
        - "X分钟前"
        - "X小时前"
        - "今天 HH:MM"
        - "昨天 HH:MM"
        - "MM-DD"（当年）
        - "YYYY-MM-DD"
        - 标准格式 "Wed Oct 18 10:30:00 +0800 2023"
        """
        if not time_str or not isinstance(time_str, str):
            return datetime.now()

        time_str = time_str.strip()
        now = datetime.now()

        # "刚刚"
        if time_str == "刚刚":
            return now

        # "X分钟前"
        match = re.match(r"(\d+)\s*分钟前", time_str)
        if match:
            minutes = int(match.group(1))
            return now - timedelta(minutes=minutes)

        # "X小时前"
        match = re.match(r"(\d+)\s*小时前", time_str)
        if match:
            hours = int(match.group(1))
            return now - timedelta(hours=hours)

        # "今天 HH:MM"
        match = re.match(r"今天\s*(\d{1,2}):(\d{2})", time_str)
        if match:
            try:
                return now.replace(
                    hour=int(match.group(1)),
                    minute=int(match.group(2)),
                    second=0, microsecond=0,
                )
            except ValueError:
                pass

        # "昨天 HH:MM"
        match = re.match(r"昨天\s*(\d{1,2}):(\d{2})", time_str)
        if match:
            yesterday = now - timedelta(days=1)
            try:
                return yesterday.replace(
                    hour=int(match.group(1)),
                    minute=int(match.group(2)),
                    second=0, microsecond=0,
                )
            except ValueError:
                pass

        # "YYYY-MM-DD" 或 "YYYY-MM-DD HH:MM"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        # "MM-DD"（当年）
        match = re.match(r"^(\d{1,2})-(\d{1,2})$", time_str)
        if match:
            month, day = int(match.group(1)), int(match.group(2))
            try:
                result = now.replace(
                    month=month, day=day,
                    hour=0, minute=0, second=0, microsecond=0,
                )
                if result > now:
                    result = result.replace(year=now.year - 1)
                return result
            except ValueError:
                pass

        # 英文标准格式 "Wed Oct 18 10:30:00 +0800 2023"
        try:
            # 去掉时区偏移再解析
            cleaned = re.sub(r"\+\d{4}\s*", "", time_str)
            return datetime.strptime(cleaned.strip(), "%a %b %d %H:%M:%S %Y")
        except ValueError:
            pass

        logger.debug(f"[weibo] 无法解析时间: '{time_str}'，使用当前时间")
        return now

    @staticmethod
    def _safe_int(value) -> int:
        """安全地将值转换为整数

        处理：数字字符串、带单位的数字（如 '1.2万'）、None等。
        """
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
        """关闭HTTP会话，释放连接池资源"""
        try:
            self.session.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        self.close()
