"""市值风云（shizifengyun.com）文章采集器

从市值风云网站抓取专业财经分析文章，用于社交情绪分析。
市值风云是专业金融媒体，文章质量高但数量较少，适合作为补充数据源。

采集策略：
1. 优先尝试搜索API获取结构化数据
2. 备用方案：HTML页面解析搜索结果
3. 站点不可达时优雅降级
"""

import re
import json
import logging
import urllib.parse
import warnings
from datetime import datetime
from typing import List, Optional

import requests
from urllib3.exceptions import InsecureRequestWarning
from bs4 import BeautifulSoup

from social.base_source import BaseSocialSource
from storage.models import SocialPost

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

logger = logging.getLogger(__name__)


class ShizifengyunCrawler(BaseSocialSource):
    """市值风云数据源

    市值风云是专业金融分析媒体，文章由分析师撰写，
    信号质量高于散户讨论平台，但文章数量相对较少。
    """

    BASE_URL = "https://www.shizifengyun.com"
    SEARCH_API_URL = "https://www.shizifengyun.com/api/search"
    SEARCH_PAGE_URL = "https://www.shizifengyun.com/search"
    ARTICLE_URL_TEMPLATE = "https://www.shizifengyun.com/article/{article_id}"

    def __init__(self, min_interval: float = 2.0, max_retries: int = 3,
                 timeout: int = 15):
        """初始化市值风云采集器

        Args:
            min_interval: 请求最小间隔（秒），默认2秒
            max_retries: 最大重试次数
            timeout: 请求超时时间（秒）
        """
        super().__init__(
            name="shizifengyun",
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
        )
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update(self._build_headers({
            "Referer": self.BASE_URL + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;"
                      "q=0.9,application/json,*/*;q=0.8",
        }))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_stock_posts(self, stock_code: str, stock_name: str = "",
                          limit: int = 30) -> List[SocialPost]:
        """获取指定股票的市值风云文章

        使用股票名称进行搜索（市值风云以文章为主，按名称搜索更有效）。
        如果没有股票名称，则使用股票代码搜索。

        Args:
            stock_code: 股票代码（纯数字，如 '600519'）
            stock_name: 股票名称（如 '贵州茅台'）
            limit: 最多获取条数
        Returns:
            文章列表（转为SocialPost格式）
        """
        keyword = stock_name if stock_name else stock_code
        posts: List[SocialPost] = []

        # 策略1：尝试搜索API
        try:
            posts = self._retry_request(
                self._fetch_via_api, keyword, stock_code, stock_name, limit
            )
        except Exception as e:
            logger.warning(
                f"[shizifengyun] API搜索 '{keyword}' 失败: {e}，尝试HTML解析"
            )

        # 策略2：备用HTML解析
        if not posts:
            try:
                posts = self._retry_request(
                    self._fetch_via_html, keyword, stock_code, stock_name, limit
                )
            except Exception as e:
                logger.warning(
                    f"[shizifengyun] HTML解析搜索 '{keyword}' 也失败: {e}"
                )

        # 策略3：尝试用股票代码搜索（如果之前用名称搜索没结果）
        if not posts and stock_name and stock_code:
            try:
                posts = self._retry_request(
                    self._fetch_via_api, stock_code, stock_code, stock_name, limit
                )
            except Exception as e:
                logger.debug(
                    f"[shizifengyun] 代码搜索 '{stock_code}' 也失败: {e}"
                )

        if posts:
            logger.info(
                f"[shizifengyun] 获取 {stock_code} {stock_name} 文章 {len(posts)} 篇"
            )
        else:
            logger.debug(
                f"[shizifengyun] 未获取到 {stock_code} {stock_name} 的文章"
            )

        return posts[:limit]

    def health_check(self) -> bool:
        """检查市值风云是否可用

        用"贵州茅台"做探活测试。由于该站点可能不稳定，
        health_check失败时优雅返回False。
        """
        try:
            self._rate_limit()
            self.session.headers["User-Agent"] = self._get_random_ua()

            # 先尝试访问首页，确认站点可达
            resp = self.session.get(
                self.BASE_URL,
                timeout=self.timeout,
                verify=False,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"[shizifengyun] 首页返回状态码 {resp.status_code}"
                )
                return False

            # 尝试搜索贵州茅台
            posts = self.fetch_stock_posts("600519", "贵州茅台", limit=3)
            ok = len(posts) > 0
            if ok:
                logger.info("[shizifengyun] 健康检查通过")
            else:
                # 站点可达但搜索无结果，可能是正常情况（API变化等）
                logger.warning(
                    "[shizifengyun] 健康检查：站点可达但未获取到文章"
                )
            return ok
        except requests.exceptions.ConnectionError:
            logger.warning("[shizifengyun] 健康检查失败：站点不可达")
            return False
        except requests.exceptions.Timeout:
            logger.warning("[shizifengyun] 健康检查失败：请求超时")
            return False
        except Exception as e:
            logger.warning(f"[shizifengyun] 健康检查异常: {e}")
            return False

    # ------------------------------------------------------------------
    # Private: API-based fetching
    # ------------------------------------------------------------------

    def _fetch_via_api(self, keyword: str, stock_code: str,
                       stock_name: str, limit: int) -> List[SocialPost]:
        """通过市值风云搜索API获取文章

        尝试调用 /api/search 接口获取JSON格式的搜索结果。
        """
        self._rate_limit()
        self.session.headers["User-Agent"] = self._get_random_ua()

        params = {
            "keyword": keyword,
            "page": 1,
            "pageSize": min(limit, 50),
        }

        resp = self.session.get(
            self.SEARCH_API_URL,
            params=params,
            timeout=self.timeout,
        )

        # Handle rate limiting (429) with a brief pause
        if resp.status_code == 429:
            import time
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.warning(
                f"[shizifengyun] 触发限流(429)，等待 {retry_after} 秒"
            )
            time.sleep(min(retry_after, 30))
            raise requests.exceptions.HTTPError(
                f"429 Too Many Requests", response=resp
            )

        resp.raise_for_status()
        resp.encoding = "utf-8"

        # 尝试解析JSON响应
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            # 如果不是JSON响应，可能API不存在，抛出异常让调用方切换策略
            raise ValueError("API未返回JSON数据，可能需要HTML解析")

        return self._parse_api_response(data, stock_code, stock_name)

    def _parse_api_response(self, data: dict, stock_code: str,
                            stock_name: str) -> List[SocialPost]:
        """解析搜索API返回的JSON数据"""
        posts: List[SocialPost] = []

        if not isinstance(data, dict):
            return posts

        # 尝试多种可能的数据结构
        article_list = None
        for key_path in [
            lambda d: d.get("data", {}).get("list", []),
            lambda d: d.get("data", {}).get("items", []),
            lambda d: d.get("data", {}).get("articles", []),
            lambda d: d.get("data", []) if isinstance(d.get("data"), list) else None,
            lambda d: d.get("list", []),
            lambda d: d.get("items", []),
            lambda d: d.get("articles", []),
            lambda d: d.get("result", {}).get("list", []),
            lambda d: d.get("result", []) if isinstance(d.get("result"), list) else None,
        ]:
            try:
                result = key_path(data)
                if result and isinstance(result, list):
                    article_list = result
                    break
            except (AttributeError, TypeError):
                continue

        if not article_list:
            logger.debug(
                f"[shizifengyun] API响应中未找到文章列表, "
                f"keys={list(data.keys()) if isinstance(data, dict) else type(data)}"
            )
            return posts

        for item in article_list:
            try:
                post = self._parse_article_item(item, stock_code, stock_name)
                if post:
                    posts.append(post)
            except Exception as e:
                logger.debug(f"[shizifengyun] 解析单篇文章失败: {e}")
                continue

        return posts

    def _parse_article_item(self, item: dict, stock_code: str,
                            stock_name: str) -> Optional[SocialPost]:
        """解析单篇文章数据为SocialPost"""
        if not isinstance(item, dict):
            return None

        # 标题（必须字段）
        title = (
            item.get("title", "")
            or item.get("Title", "")
            or item.get("article_title", "")
        ).strip()
        if not title:
            return None

        # 清理HTML标签
        title = self._strip_html(title)

        # 内容/摘要
        content = (
            item.get("summary", "")
            or item.get("abstract", "")
            or item.get("description", "")
            or item.get("content", "")
            or item.get("intro", "")
            or ""
        ).strip()
        content = self._strip_html(content)

        # 作者
        author = (
            item.get("author", "")
            or item.get("author_name", "")
            or item.get("writer", "")
            or item.get("nickname", "")
            or "市值风云"
        )
        if isinstance(author, dict):
            author = author.get("name", "") or author.get("nickname", "") or "市值风云"
        author = str(author).strip()

        # 发布时间
        raw_time = (
            item.get("publish_time", "")
            or item.get("published_at", "")
            or item.get("create_time", "")
            or item.get("created_at", "")
            or item.get("date", "")
            or item.get("time", "")
            or ""
        )
        publish_time = self._parse_time(raw_time)

        # 文章URL
        article_id = str(
            item.get("id", "")
            or item.get("article_id", "")
            or item.get("aid", "")
            or ""
        )
        url = item.get("url", "") or item.get("link", "")
        if not url and article_id:
            url = self.ARTICLE_URL_TEMPLATE.format(article_id=article_id)

        # 阅读/评论数
        read_count = self._safe_int(
            item.get("read_count", 0)
            or item.get("view_count", 0)
            or item.get("views", 0)
        )
        comment_count = self._safe_int(
            item.get("comment_count", 0)
            or item.get("comments", 0)
        )
        like_count = self._safe_int(
            item.get("like_count", 0)
            or item.get("likes", 0)
        )

        return SocialPost(
            source="shizifengyun",
            stock_code=stock_code,
            stock_name=stock_name,
            title=title,
            content=content,
            author=author,
            publish_time=publish_time,
            url=url,
            read_count=read_count,
            comment_count=comment_count,
            like_count=like_count,
        )

    # ------------------------------------------------------------------
    # Private: HTML-based fetching (fallback)
    # ------------------------------------------------------------------

    def _fetch_via_html(self, keyword: str, stock_code: str,
                        stock_name: str, limit: int) -> List[SocialPost]:
        """通过解析搜索结果HTML页面获取文章"""
        self._rate_limit()
        self.session.headers["User-Agent"] = self._get_random_ua()

        params = {"keyword": keyword}
        url = f"{self.SEARCH_PAGE_URL}?{urllib.parse.urlencode(params)}"

        resp = self.session.get(
            url,
            timeout=self.timeout,
            verify=False,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"

        posts = self._parse_search_html(resp.text, stock_code, stock_name)
        return posts[:limit]

    def _parse_search_html(self, html: str, stock_code: str,
                           stock_name: str) -> List[SocialPost]:
        """解析搜索结果页面HTML"""
        posts: List[SocialPost] = []

        # 先尝试从HTML中提取嵌入的JSON数据（SPA/SSR常见模式）
        json_posts = self._extract_embedded_json(html, stock_code, stock_name)
        if json_posts:
            return json_posts

        # 回退到传统HTML解析
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.warning(f"[shizifengyun] HTML解析失败: {e}")
            return posts

        # 尝试多种可能的文章容器选择器
        article_selectors = [
            "div.article-item",
            "div.search-item",
            "div.article-list-item",
            "div.post-item",
            "article",
            "div.item",
            "li.article",
            "div.news-item",
            "div.content-item",
        ]

        articles = []
        for selector in article_selectors:
            articles = soup.select(selector)
            if articles:
                break

        if not articles:
            # 最后尝试：查找所有包含标题链接的容器
            articles = soup.select("a[href*='article'], a[href*='post'], a[href*='news']")
            if articles:
                for a_tag in articles[:30]:
                    title = a_tag.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue
                    href = a_tag.get("href", "")
                    if href and not href.startswith("http"):
                        href = self.BASE_URL + href

                    posts.append(SocialPost(
                        source="shizifengyun",
                        stock_code=stock_code,
                        stock_name=stock_name,
                        title=self._strip_html(title),
                        content="",
                        author="市值风云",
                        publish_time=datetime.now(),
                        url=href,
                    ))
                return posts

        for article in articles:
            try:
                post = self._parse_html_article(article, stock_code, stock_name)
                if post:
                    posts.append(post)
            except Exception as e:
                logger.debug(f"[shizifengyun] 解析HTML文章条目失败: {e}")
                continue

        return posts

    def _extract_embedded_json(self, html: str, stock_code: str,
                               stock_name: str) -> List[SocialPost]:
        """尝试从HTML页面中提取嵌入的JSON数据

        现代SPA框架常将数据嵌入在 __NEXT_DATA__、window.__data__ 等变量中。
        """
        posts: List[SocialPost] = []

        # 常见SSR/SPA框架的数据嵌入模式
        patterns = [
            r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;',
            r'window\.__data__\s*=\s*(\{.*?\})\s*;',
            r'window\.__NUXT__\s*=\s*(\{.*?\})\s*;',
            r'var\s+searchData\s*=\s*(\{.*?\})\s*;',
            r'var\s+articleList\s*=\s*(\[.*?\])\s*;',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # 递归搜索文章列表
                    article_list = self._find_articles_in_data(data)
                    if article_list:
                        for item in article_list:
                            post = self._parse_article_item(
                                item, stock_code, stock_name
                            )
                            if post:
                                posts.append(post)
                        if posts:
                            return posts
                except (json.JSONDecodeError, TypeError):
                    continue

        return posts

    def _find_articles_in_data(self, data, depth: int = 0) -> Optional[list]:
        """递归搜索嵌套数据中的文章列表

        在JSON数据结构中查找看起来像文章列表的数组。
        """
        if depth > 5:
            return None

        if isinstance(data, list) and len(data) > 0:
            # 检查列表中的元素是否像文章
            if isinstance(data[0], dict) and any(
                k in data[0] for k in ("title", "Title", "article_title")
            ):
                return data

        if isinstance(data, dict):
            # 优先检查常见的列表键名
            for key in ("articles", "list", "items", "posts", "data",
                         "searchResults", "results", "records"):
                if key in data:
                    result = self._find_articles_in_data(data[key], depth + 1)
                    if result:
                        return result

            # 递归搜索其他键
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    result = self._find_articles_in_data(value, depth + 1)
                    if result:
                        return result

        return None

    def _parse_html_article(self, element, stock_code: str,
                            stock_name: str) -> Optional[SocialPost]:
        """从HTML元素中解析单篇文章"""
        # 提取标题
        title_tag = (
            element.select_one("h2 a, h3 a, h4 a, .title a, .article-title a")
            or element.select_one("h2, h3, h4, .title, .article-title")
            or element.select_one("a")
        )
        if not title_tag:
            return None

        title = title_tag.get_text(strip=True)
        if not title or len(title) < 4:
            return None

        # 提取URL
        url = ""
        a_tag = title_tag if title_tag.name == "a" else title_tag.find("a")
        if a_tag:
            href = a_tag.get("href", "")
            if href:
                url = href if href.startswith("http") else self.BASE_URL + href

        # 提取摘要
        summary_tag = element.select_one(
            ".summary, .abstract, .desc, .description, .intro, p"
        )
        content = summary_tag.get_text(strip=True) if summary_tag else ""

        # 提取作者
        author_tag = element.select_one(
            ".author, .writer, .user-name, .nickname, span.name"
        )
        author = author_tag.get_text(strip=True) if author_tag else "市值风云"

        # 提取时间
        time_tag = element.select_one(
            ".time, .date, .publish-time, time, .created-at, span.datetime"
        )
        raw_time = ""
        if time_tag:
            raw_time = time_tag.get("datetime", "") or time_tag.get_text(strip=True)
        publish_time = self._parse_time(raw_time)

        return SocialPost(
            source="shizifengyun",
            stock_code=stock_code,
            stock_name=stock_name,
            title=self._strip_html(title),
            content=self._strip_html(content),
            author=author,
            publish_time=publish_time,
            url=url,
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time(time_str) -> datetime:
        """解析市值风云的各种时间格式

        支持格式：
        - '2024-01-15 10:30:00'
        - '2024-01-15T10:30:00'
        - '2024-01-15'
        - '2024/01/15'
        - '3小时前'
        - '昨天'
        - Unix时间戳（整数或字符串）
        """
        if not time_str:
            return datetime.now()

        # 处理Unix时间戳（整数形式）
        if isinstance(time_str, (int, float)):
            try:
                # 毫秒时间戳
                if time_str > 1e12:
                    return datetime.fromtimestamp(time_str / 1000)
                return datetime.fromtimestamp(time_str)
            except (ValueError, OSError):
                return datetime.now()

        if not isinstance(time_str, str):
            return datetime.now()

        time_str = time_str.strip()
        if not time_str:
            return datetime.now()

        # 尝试数字时间戳字符串
        try:
            ts = float(time_str)
            if ts > 1e12:
                return datetime.fromtimestamp(ts / 1000)
            if ts > 1e9:
                return datetime.fromtimestamp(ts)
        except ValueError:
            pass

        # ISO格式及常见格式
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S+08:00",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d",
            "%Y.%m.%d",
        ):
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        # 相对时间：N分钟前、N小时前、N天前
        relative_match = re.match(r"(\d+)\s*(分钟|小时|天|秒)前", time_str)
        if relative_match:
            from datetime import timedelta
            amount = int(relative_match.group(1))
            unit = relative_match.group(2)
            delta_map = {"秒": timedelta(seconds=amount),
                         "分钟": timedelta(minutes=amount),
                         "小时": timedelta(hours=amount),
                         "天": timedelta(days=amount)}
            return datetime.now() - delta_map.get(unit, timedelta())

        if "刚刚" in time_str:
            return datetime.now()

        if "昨天" in time_str:
            from datetime import timedelta
            return datetime.now() - timedelta(days=1)

        if "前天" in time_str:
            from datetime import timedelta
            return datetime.now() - timedelta(days=2)

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
        # 去除HTML标签
        clean = re.sub(r'<[^>]+>', '', text)
        # 去除HTML实体
        clean = re.sub(r'&[a-zA-Z]+;', ' ', clean)
        clean = re.sub(r'&#\d+;', ' ', clean)
        # 合并空白
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

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
