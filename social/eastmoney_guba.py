"""东方财富股吧数据采集器

从东方财富股吧（guba.eastmoney.com）抓取个股讨论帖子，
用于社交情绪分析。使用股吧帖子列表API获取结构化数据。
"""

import re
import logging
from datetime import datetime
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from social.base_source import BaseSocialSource
from storage.models import SocialPost

logger = logging.getLogger(__name__)


class EastMoneyGuba(BaseSocialSource):
    """东方财富股吧数据源

    采集策略：
    1. 优先使用股吧帖子列表API（返回JSON，结构化程度高）
    2. 备用方案：解析股吧HTML页面
    """

    # 股吧API基础URL
    API_URL = "https://guba.eastmoney.com/interface/GetData.aspx"

    # 股吧帖子列表页URL（备用HTML解析）
    LIST_URL = "https://guba.eastmoney.com/list,{stock_code}.html"
    LIST_URL_PAGED = "https://guba.eastmoney.com/list,{stock_code},f_{page}.html"

    # 单条帖子URL模板
    POST_URL_TEMPLATE = "https://guba.eastmoney.com/news,{stock_code},{post_id}.html"

    # 股吧新版API（帖子列表）
    NEW_API_URL = "https://gbapi.eastmoney.com/ssguba/api"

    def __init__(self, min_interval: float = 2.0, max_retries: int = 3,
                 timeout: int = 15):
        """初始化东方财富股吧采集器

        Args:
            min_interval: 请求最小间隔（秒），默认2秒避免被封
            max_retries: 最大重试次数
            timeout: 请求超时时间（秒）
        """
        super().__init__(
            name="eastmoney",
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
        )
        self.session = requests.Session()
        self.session.headers.update(self._build_headers({
            "Referer": "https://guba.eastmoney.com/",
        }))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_stock_posts(self, stock_code: str, stock_name: str = "",
                          limit: int = 30) -> List[SocialPost]:
        """获取指定股票的股吧帖子

        Args:
            stock_code: 股票代码（纯数字，如 '600519'）
            stock_name: 股票名称（可选）
            limit: 最多获取条数
        Returns:
            帖子列表
        """
        posts: List[SocialPost] = []

        # 优先尝试API方式
        try:
            posts = self._retry_request(
                self._fetch_via_api, stock_code, stock_name, limit
            )
        except Exception as e:
            logger.warning(
                f"[eastmoney] API方式获取 {stock_code} 失败: {e}，尝试HTML解析"
            )

        # 如果API方式失败或结果为空，使用HTML解析作为备用
        if not posts:
            try:
                posts = self._retry_request(
                    self._fetch_via_html, stock_code, stock_name, limit
                )
            except Exception as e:
                logger.error(f"[eastmoney] HTML方式获取 {stock_code} 也失败: {e}")
                return []

        logger.info(
            f"[eastmoney] 获取 {stock_code} {stock_name} 帖子 {len(posts)} 条"
        )
        return posts[:limit]

    def health_check(self) -> bool:
        """检查东方财富股吧是否可用

        用贵州茅台（600519）做探活测试。
        """
        try:
            posts = self.fetch_stock_posts("600519", "贵州茅台", limit=5)
            ok = len(posts) > 0
            if ok:
                logger.info("[eastmoney] 健康检查通过")
            else:
                logger.warning("[eastmoney] 健康检查失败：未获取到帖子")
            return ok
        except Exception as e:
            logger.error(f"[eastmoney] 健康检查异常: {e}")
            return False

    # ------------------------------------------------------------------
    # Private: API-based fetching
    # ------------------------------------------------------------------

    def _fetch_via_api(self, stock_code: str, stock_name: str,
                       limit: int) -> List[SocialPost]:
        """通过东方财富股吧API获取帖子列表"""
        self._rate_limit()

        # 刷新UA以降低被封风险
        self.session.headers["User-Agent"] = self._get_random_ua()

        params = {
            "param": (
                f"postListByCode,code={stock_code},"
                f"orderType=0,sortType=1,"
                f"pageIndex=1,pageSize={min(limit, 100)}"
            ),
            "path": "dbq/getstockbar",
            "env": 2,
        }

        resp = self.session.get(
            self.API_URL,
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"

        data = resp.json()
        return self._parse_api_response(data, stock_code, stock_name)

    def _parse_api_response(self, data: dict, stock_code: str,
                            stock_name: str) -> List[SocialPost]:
        """解析API返回的JSON数据"""
        posts: List[SocialPost] = []

        # API返回格式可能有多层嵌套，尝试不同的数据路径
        post_list = None

        if isinstance(data, dict):
            # 尝试 data -> re -> data（常见嵌套格式）
            if "re" in data and isinstance(data["re"], list):
                post_list = data["re"]
            elif "data" in data:
                inner = data["data"]
                if isinstance(inner, list):
                    post_list = inner
                elif isinstance(inner, dict):
                    for key in ("re", "list", "items", "rows"):
                        if key in inner and isinstance(inner[key], list):
                            post_list = inner[key]
                            break

        if not post_list:
            logger.debug(f"[eastmoney] API返回数据中未找到帖子列表, keys={list(data.keys()) if isinstance(data, dict) else type(data)}")
            return posts

        for item in post_list:
            try:
                post = self._parse_api_item(item, stock_code, stock_name)
                if post:
                    posts.append(post)
            except Exception as e:
                logger.debug(f"[eastmoney] 解析单条帖子失败: {e}")
                continue

        return posts

    def _parse_api_item(self, item: dict, stock_code: str,
                        stock_name: str) -> Optional[SocialPost]:
        """解析API返回的单条帖子数据"""
        # 标题是必须字段
        title = (
            item.get("post_title", "")
            or item.get("title", "")
            or item.get("Title", "")
        ).strip()
        if not title:
            return None

        # 作者
        author = (
            item.get("post_user", {}).get("user_nickname", "")
            if isinstance(item.get("post_user"), dict)
            else item.get("user_nickname", "")
            or item.get("author", "")
            or item.get("Author", "")
            or "匿名"
        )

        # 发布时间
        publish_time = self._parse_time(
            item.get("post_publish_time")
            or item.get("publish_time")
            or item.get("PublishTime")
            or item.get("post_display_time")
            or ""
        )

        # 帖子ID -> URL
        post_id = str(
            item.get("post_id")
            or item.get("postid")
            or item.get("PostId")
            or ""
        )
        url = ""
        if post_id:
            url = self.POST_URL_TEMPLATE.format(
                stock_code=stock_code, post_id=post_id
            )

        # 互动数据
        read_count = self._safe_int(
            item.get("post_click_count")
            or item.get("click_count")
            or item.get("ClickCount")
            or 0
        )
        comment_count = self._safe_int(
            item.get("post_comment_count")
            or item.get("comment_count")
            or item.get("CommentCount")
            or 0
        )

        content = (
            item.get("post_content", "")
            or item.get("content", "")
            or item.get("Content", "")
            or ""
        ).strip()

        return SocialPost(
            source="eastmoney",
            stock_code=stock_code,
            stock_name=stock_name,
            title=title,
            content=content,
            author=str(author),
            publish_time=publish_time,
            url=url,
            read_count=read_count,
            comment_count=comment_count,
        )

    # ------------------------------------------------------------------
    # Private: HTML-based fetching (fallback)
    # ------------------------------------------------------------------

    def _fetch_via_html(self, stock_code: str, stock_name: str,
                        limit: int) -> List[SocialPost]:
        """通过解析股吧HTML页面获取帖子（备用方案）"""
        posts: List[SocialPost] = []
        pages_needed = max(1, (limit + 29) // 30)  # 每页约30条

        for page in range(1, pages_needed + 1):
            if len(posts) >= limit:
                break

            self._rate_limit()
            self.session.headers["User-Agent"] = self._get_random_ua()

            if page == 1:
                url = self.LIST_URL.format(stock_code=stock_code)
            else:
                url = self.LIST_URL_PAGED.format(
                    stock_code=stock_code, page=page
                )

            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            resp.encoding = "utf-8"

            page_posts = self._parse_html_page(
                resp.text, stock_code, stock_name
            )
            posts.extend(page_posts)

            if not page_posts:
                # 当前页为空说明没有更多数据
                break

        return posts[:limit]

    def _parse_html_page(self, html: str, stock_code: str,
                         stock_name: str) -> List[SocialPost]:
        """解析股吧列表页HTML，提取帖子信息"""
        posts: List[SocialPost] = []
        soup = BeautifulSoup(html, "html.parser")

        # 股吧帖子列表通常在 <div class="articleh"> 或 <div class="listitem">
        # 或表格 <table id="mainlist"> 的行中
        rows = (
            soup.select("div.articleh")
            or soup.select("div.listitem")
            or soup.select("div.normal_post")
        )

        # 如果上述选择器都不命中，尝试通用的帖子链接提取
        if not rows:
            rows = soup.select("ul.newlist li") or []

        for row in rows:
            try:
                post = self._parse_html_row(row, stock_code, stock_name)
                if post:
                    posts.append(post)
            except Exception as e:
                logger.debug(f"[eastmoney] HTML行解析失败: {e}")
                continue

        return posts

    def _parse_html_row(self, row, stock_code: str,
                        stock_name: str) -> Optional[SocialPost]:
        """解析单行HTML帖子数据"""
        # 提取标题和链接
        link_tag = (
            row.select_one("span.l3 a")
            or row.select_one("a.note")
            or row.select_one("a[href*='/news,']")
            or row.select_one("a[title]")
        )
        if not link_tag:
            return None

        title = (link_tag.get("title") or link_tag.get_text()).strip()
        if not title:
            return None

        # 过滤置顶/广告贴（常见特征）
        row_text = row.get_text()
        if any(kw in title for kw in ("广告", "公告", "问董秘")):
            return None

        href = link_tag.get("href", "")
        url = href if href.startswith("http") else f"https://guba.eastmoney.com{href}"

        # 阅读数
        read_tag = row.select_one("span.l1") or row.select_one(".read")
        read_count = self._safe_int(
            read_tag.get_text().strip() if read_tag else 0
        )

        # 评论数
        comment_tag = row.select_one("span.l2") or row.select_one(".reply")
        comment_count = self._safe_int(
            comment_tag.get_text().strip() if comment_tag else 0
        )

        # 作者
        author_tag = (
            row.select_one("span.l4 a")
            or row.select_one(".author a")
            or row.select_one("a.name")
        )
        author = author_tag.get_text().strip() if author_tag else "匿名"

        # 发布时间
        time_tag = (
            row.select_one("span.l5")
            or row.select_one("span.l6")
            or row.select_one(".update")
            or row.select_one(".time")
        )
        time_str = time_tag.get_text().strip() if time_tag else ""
        publish_time = self._parse_time(time_str)

        return SocialPost(
            source="eastmoney",
            stock_code=stock_code,
            stock_name=stock_name,
            title=title,
            content="",
            author=author,
            publish_time=publish_time,
            url=url,
            read_count=read_count,
            comment_count=comment_count,
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time(time_str: str) -> datetime:
        """解析东方财富的各种时间格式

        支持格式：
        - '2024-01-15 10:30:00'
        - '2024-01-15 10:30'
        - '01-15 10:30'  （无年份，补当年）
        - '10:30'        （仅时间，补当天）
        - '今天 10:30'
        - '昨天 10:30'
        """
        if not time_str or not isinstance(time_str, str):
            return datetime.now()

        time_str = time_str.strip()
        now = datetime.now()

        # 完整日期时间：2024-01-15 10:30:00
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                     "%Y/%m/%d %H:%M"):
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        # 无年份：01-15 10:30
        match = re.match(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", time_str)
        if match:
            month, day, hour, minute = (int(g) for g in match.groups())
            try:
                result = now.replace(month=month, day=day, hour=hour,
                                     minute=minute, second=0, microsecond=0)
                # 如果解析出来的日期在未来，则回退到去年
                if result > now:
                    result = result.replace(year=now.year - 1)
                return result
            except ValueError:
                pass

        # 仅时间：10:30
        match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
            try:
                return now.replace(hour=hour, minute=minute, second=0,
                                   microsecond=0)
            except ValueError:
                pass

        # 今天/昨天
        if "今天" in time_str:
            t_match = re.search(r"(\d{1,2}):(\d{2})", time_str)
            if t_match:
                try:
                    return now.replace(
                        hour=int(t_match.group(1)),
                        minute=int(t_match.group(2)),
                        second=0, microsecond=0,
                    )
                except ValueError:
                    pass

        if "昨天" in time_str:
            from datetime import timedelta
            yesterday = now - timedelta(days=1)
            t_match = re.search(r"(\d{1,2}):(\d{2})", time_str)
            if t_match:
                try:
                    return yesterday.replace(
                        hour=int(t_match.group(1)),
                        minute=int(t_match.group(2)),
                        second=0, microsecond=0,
                    )
                except ValueError:
                    pass

        # 无法解析，返回当前时间
        logger.debug(f"[eastmoney] 无法解析时间: '{time_str}'，使用当前时间")
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

        # 处理中文单位：万、亿
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
    def get_market_prefix(stock_code: str) -> str:
        """根据股票代码判断市场前缀

        上海（6开头）: 'sh' / '1.{code}'
        深圳（0、3开头）: 'sz' / '0.{code}'
        北交所（8、4开头）: 'bj' / '0.{code}'
        """
        if stock_code.startswith("6"):
            return "sh"
        elif stock_code.startswith(("0", "3")):
            return "sz"
        elif stock_code.startswith(("8", "4")):
            return "bj"
        return "sh"

    @staticmethod
    def get_secid(stock_code: str) -> str:
        """生成东方财富的secid格式（如 '1.600519'）

        上海: 1.{code}
        深圳/北交所: 0.{code}
        """
        if stock_code.startswith("6"):
            return f"1.{stock_code}"
        return f"0.{stock_code}"

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
