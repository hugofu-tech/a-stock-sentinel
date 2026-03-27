"""
特朗普社交媒体监控器
轮询Truth Social和X(Twitter)获取特朗普最新发帖。

数据源策略（优先级从高到低）：
- Truth Social:
  1. Playwright浏览器渲染（最可靠，绕过403）
  2. RSS订阅
  3. Mastodon兼容API
  4. requests网页抓取
- X/Twitter:
  1. Playwright浏览器渲染（无需API Key）
  2. Twitter API v2（需Bearer Token）

统一输出格式：
{
    'id': str,
    'source': 'truth_social' | 'twitter',
    'content': str,
    'created_at': str (ISO格式),
    'url': str,
    'media_urls': list[str],
    'is_repost': bool
}
"""

import json
import logging
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from trump_config import (
    TWITTER_BEARER_TOKEN,
    TRUMP_TWITTER_USER_ID,
    TRUMP_TWITTER_USERNAME,
    TRUTH_SOCIAL_USERNAME,
    TRUTH_SOCIAL_BASE_URL,
    PLAYWRIGHT_HEADLESS,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# ============================================================
# Playwright浏览器引擎（首选方案）
# ============================================================

def _get_playwright_browser():
    """启动Playwright浏览器实例。"""
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=PLAYWRIGHT_HEADLESS,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
            ]
        )
        return pw, browser
    except Exception as e:
        logger.debug(f"Playwright启动失败: {e}")
        return None, None


class PlaywrightTruthSocialMonitor:
    """通过Playwright浏览器渲染获取Truth Social推文（最可靠）。"""

    def fetch_posts(self, limit=20):
        """用浏览器访问Truth Social个人页面，等待JS渲染后提取推文。"""
        pw, browser = None, None
        try:
            pw, browser = _get_playwright_browser()
            if not browser:
                return []

            page = browser.new_page(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/131.0.0.0 Safari/537.36'
            )

            url = f"{TRUTH_SOCIAL_BASE_URL}/@{TRUTH_SOCIAL_USERNAME}"
            logger.info(f"Playwright访问: {url}")
            page.goto(url, timeout=30000, wait_until='networkidle')
            page.wait_for_timeout(3000)  # 额外等待JS渲染

            posts = []

            # Truth Social基于Mastodon，推文在特定DOM结构中
            # 尝试多种选择器
            selectors = [
                'div[data-testid="status"]',
                'article',
                '.status',
                'div.status-content',
                '[class*="status"]',
            ]

            status_elements = []
            for sel in selectors:
                status_elements = page.query_selector_all(sel)
                if status_elements:
                    logger.debug(f"选择器 '{sel}' 匹配到 {len(status_elements)} 个元素")
                    break

            if not status_elements:
                # 回退：从页面JSON数据提取
                posts = self._extract_from_page_data(page, limit)
                if posts:
                    logger.info(f"Playwright Truth Social (JSON): 获取 {len(posts)} 条")
                    return posts

                # 再回退：从整个页面文本提取
                logger.debug("尝试从页面文本提取推文")
                posts = self._extract_from_page_text(page, limit)
                if posts:
                    logger.info(f"Playwright Truth Social (文本): 获取 {len(posts)} 条")
                    return posts

                logger.warning("Playwright未找到任何推文元素")
                return []

            # 从DOM元素中提取推文
            for elem in status_elements[:limit]:
                try:
                    content = elem.inner_text()
                    if not content or len(content.strip()) < 5:
                        continue

                    # 尝试获取链接
                    link = elem.query_selector('a[href*="/@"]')
                    post_url = link.get_attribute('href') if link else ''
                    post_id = self._extract_id(post_url)

                    # 尝试获取时间
                    time_elem = elem.query_selector('time')
                    created_at = ''
                    if time_elem:
                        created_at = time_elem.get_attribute('datetime') or ''

                    posts.append({
                        'id': f"ts_{post_id}",
                        'source': 'truth_social',
                        'content': content.strip(),
                        'created_at': created_at or datetime.now(timezone.utc).isoformat(),
                        'url': f"{TRUTH_SOCIAL_BASE_URL}{post_url}" if post_url else url,
                        'media_urls': [],
                        'is_repost': False,
                    })
                except Exception:
                    continue

            logger.info(f"Playwright Truth Social (DOM): 获取 {len(posts)} 条")
            return posts

        except Exception as e:
            logger.error(f"Playwright Truth Social失败: {e}")
            return []
        finally:
            if browser:
                browser.close()
            if pw:
                pw.stop()

    def _extract_from_page_data(self, page, limit):
        """从页面内嵌的JSON初始数据中提取推文。"""
        posts = []
        try:
            # 很多SPA会在script标签中内嵌初始数据
            scripts = page.query_selector_all('script[type="application/json"]')
            for script in scripts:
                try:
                    data = json.loads(script.inner_text())
                    posts.extend(self._recurse_json(data, limit))
                except (json.JSONDecodeError, TypeError):
                    continue

            # 也尝试从__NEXT_DATA__或类似全局变量提取
            for var_name in ['__NEXT_DATA__', '__INITIAL_STATE__', '__PRELOADED_STATE__']:
                try:
                    data = page.evaluate(f'window.{var_name}')
                    if data:
                        posts.extend(self._recurse_json(data, limit))
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"页面数据提取失败: {e}")

        return posts[:limit]

    def _extract_from_page_text(self, page, limit):
        """从页面可见文本中提取推文（最后手段）。"""
        posts = []
        try:
            body_text = page.inner_text('body')
            # 按段落分割，过滤掉导航等短文本
            paragraphs = [p.strip() for p in body_text.split('\n\n') if len(p.strip()) > 30]

            for i, text in enumerate(paragraphs[:limit]):
                if any(skip in text.lower() for skip in ['sign in', 'log in', 'cookie', 'privacy']):
                    continue
                posts.append({
                    'id': f"ts_text_{int(time.time())}_{i}",
                    'source': 'truth_social',
                    'content': text[:500],
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'url': f"{TRUTH_SOCIAL_BASE_URL}/@{TRUTH_SOCIAL_USERNAME}",
                    'media_urls': [],
                    'is_repost': False,
                })
        except Exception as e:
            logger.debug(f"页面文本提取失败: {e}")

        return posts

    def _recurse_json(self, data, limit, depth=0):
        """递归搜索JSON数据中的推文。"""
        if depth > 10:
            return []
        posts = []
        if isinstance(data, dict):
            if 'content' in data and ('account' in data or 'user' in data):
                content = data.get('content', '')
                if content and '<' in content:
                    soup = BeautifulSoup(content, 'html.parser')
                    content = soup.get_text(strip=True)
                if content:
                    posts.append({
                        'id': f"ts_{data.get('id', hash(content))}",
                        'source': 'truth_social',
                        'content': content,
                        'created_at': data.get('created_at', ''),
                        'url': data.get('url', ''),
                        'media_urls': [],
                        'is_repost': data.get('reblog') is not None,
                    })
            for v in data.values():
                if isinstance(v, (dict, list)) and len(posts) < limit:
                    posts.extend(self._recurse_json(v, limit, depth + 1))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)) and len(posts) < limit:
                    posts.extend(self._recurse_json(item, limit, depth + 1))
        return posts[:limit]

    @staticmethod
    def _extract_id(url_or_guid):
        if not url_or_guid:
            return str(int(time.time() * 1000))
        match = re.search(r'/(\d+)', url_or_guid)
        return match.group(1) if match else str(hash(url_or_guid))


class PlaywrightTwitterMonitor:
    """通过Playwright浏览器渲染获取X/Twitter推文（无需API Key）。"""

    def fetch_posts(self, limit=10):
        """用浏览器访问X个人页面并提取推文。"""
        pw, browser = None, None
        try:
            pw, browser = _get_playwright_browser()
            if not browser:
                return []

            page = browser.new_page(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/131.0.0.0 Safari/537.36'
            )

            url = f"https://x.com/{TRUMP_TWITTER_USERNAME}"
            logger.info(f"Playwright访问: {url}")
            page.goto(url, timeout=30000, wait_until='networkidle')
            page.wait_for_timeout(5000)  # X加载较慢

            posts = []

            # X的推文在article标签或data-testid="tweet"中
            tweet_elements = page.query_selector_all('article[data-testid="tweet"]')
            if not tweet_elements:
                tweet_elements = page.query_selector_all('article')

            logger.debug(f"找到 {len(tweet_elements)} 个推文元素")

            for elem in tweet_elements[:limit]:
                try:
                    # 推文文本在 [data-testid="tweetText"] 中
                    text_elem = elem.query_selector('[data-testid="tweetText"]')
                    if not text_elem:
                        continue

                    content = text_elem.inner_text().strip()
                    if not content:
                        continue

                    # 提取推文链接获取ID
                    link = elem.query_selector('a[href*="/status/"]')
                    tweet_url = ''
                    tweet_id = str(int(time.time() * 1000))
                    if link:
                        href = link.get_attribute('href') or ''
                        match = re.search(r'/status/(\d+)', href)
                        if match:
                            tweet_id = match.group(1)
                            tweet_url = f"https://x.com{href}" if href.startswith('/') else href

                    # 获取时间
                    time_elem = elem.query_selector('time')
                    created_at = ''
                    if time_elem:
                        created_at = time_elem.get_attribute('datetime') or ''

                    # 判断是否是转发
                    retweet_indicator = elem.query_selector('[data-testid="socialContext"]')
                    is_repost = bool(retweet_indicator)

                    posts.append({
                        'id': f"tw_{tweet_id}",
                        'source': 'twitter',
                        'content': content,
                        'created_at': created_at or datetime.now(timezone.utc).isoformat(),
                        'url': tweet_url,
                        'media_urls': [],
                        'is_repost': is_repost,
                    })
                except Exception:
                    continue

            logger.info(f"Playwright Twitter: 获取 {len(posts)} 条推文")
            return posts

        except Exception as e:
            logger.error(f"Playwright Twitter失败: {e}")
            return []
        finally:
            if browser:
                browser.close()
            if pw:
                pw.stop()


# ============================================================
# HTTP备用方案（无需浏览器）
# ============================================================

class HttpTruthSocialMonitor:
    """通过HTTP请求获取Truth Social推文（备用方案）。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self.rss_url = f"{TRUTH_SOCIAL_BASE_URL}/@{TRUTH_SOCIAL_USERNAME}/rss"

    def fetch_posts(self, limit=20):
        """按优先级尝试多种HTTP方式获取推文。"""
        for method in [self._fetch_rss, self._fetch_mastodon_api, self._fetch_scrape]:
            posts = method(limit)
            if posts:
                return posts
        logger.warning("HTTP备用方案：所有Truth Social数据源均失败")
        return []

    def _fetch_rss(self, limit):
        try:
            resp = self.session.get(self.rss_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text)
            posts = []
            for item in root.findall('.//item')[:limit]:
                desc = item.findtext('description', '')
                title = item.findtext('title', '')
                content = BeautifulSoup(desc or title, 'html.parser').get_text(strip=True)
                if not content:
                    continue
                link = item.findtext('link', '')
                guid = item.findtext('guid', link)
                match = re.search(r'/(\d+)', guid or '')
                post_id = match.group(1) if match else str(hash(content))
                posts.append({
                    'id': f"ts_{post_id}", 'source': 'truth_social',
                    'content': content, 'created_at': item.findtext('pubDate', ''),
                    'url': link, 'media_urls': [], 'is_repost': False,
                })
            if posts:
                logger.info(f"HTTP RSS: 获取 {len(posts)} 条")
            return posts
        except Exception:
            return []

    def _fetch_mastodon_api(self, limit):
        try:
            lookup = self.session.get(
                f"{TRUTH_SOCIAL_BASE_URL}/api/v1/accounts/lookup",
                params={'acct': TRUTH_SOCIAL_USERNAME}, timeout=REQUEST_TIMEOUT
            )
            if lookup.status_code != 200:
                return []
            account_id = lookup.json().get('id')
            if not account_id:
                return []
            resp = self.session.get(
                f"{TRUTH_SOCIAL_BASE_URL}/api/v1/accounts/{account_id}/statuses",
                params={'limit': limit, 'exclude_replies': 'true'}, timeout=REQUEST_TIMEOUT
            )
            if resp.status_code != 200:
                return []
            posts = []
            for s in resp.json():
                content = BeautifulSoup(s.get('content', ''), 'html.parser').get_text(strip=True)
                if content:
                    posts.append({
                        'id': f"ts_{s['id']}", 'source': 'truth_social',
                        'content': content, 'created_at': s.get('created_at', ''),
                        'url': s.get('url', ''), 'media_urls': [],
                        'is_repost': s.get('reblog') is not None,
                    })
            if posts:
                logger.info(f"HTTP Mastodon API: 获取 {len(posts)} 条")
            return posts
        except Exception:
            return []

    def _fetch_scrape(self, limit):
        try:
            resp = self.session.get(
                f"{TRUTH_SOCIAL_BASE_URL}/@{TRUTH_SOCIAL_USERNAME}",
                timeout=REQUEST_TIMEOUT
            )
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, 'html.parser')
            posts = []
            for script in soup.find_all('script', type='application/json'):
                try:
                    data = json.loads(script.string or '{}')
                    # 递归查找推文对象
                    posts.extend(self._find_statuses(data, limit))
                except (json.JSONDecodeError, TypeError):
                    continue
            if posts:
                logger.info(f"HTTP Scrape (JSON): 获取 {len(posts)} 条")
            return posts[:limit]
        except Exception:
            return []

    def _find_statuses(self, data, limit, depth=0):
        if depth > 8 or not data:
            return []
        posts = []
        if isinstance(data, dict):
            if 'content' in data and 'account' in data:
                content = BeautifulSoup(data.get('content', ''), 'html.parser').get_text(strip=True)
                if content:
                    posts.append({
                        'id': f"ts_{data.get('id', hash(content))}", 'source': 'truth_social',
                        'content': content, 'created_at': data.get('created_at', ''),
                        'url': data.get('url', ''), 'media_urls': [],
                        'is_repost': data.get('reblog') is not None,
                    })
            for v in data.values():
                if len(posts) < limit:
                    posts.extend(self._find_statuses(v, limit, depth + 1))
        elif isinstance(data, list):
            for item in data:
                if len(posts) < limit:
                    posts.extend(self._find_statuses(item, limit, depth + 1))
        return posts[:limit]


class HttpTwitterMonitor:
    """通过Twitter API v2获取推文（需Bearer Token）。"""

    API_BASE = "https://api.twitter.com/2"

    def __init__(self):
        self.bearer_token = TWITTER_BEARER_TOKEN
        self.session = requests.Session()
        if self.bearer_token:
            self.session.headers.update({
                'Authorization': f'Bearer {self.bearer_token}'
            })

    def is_configured(self):
        return bool(self.bearer_token)

    def fetch_posts(self, limit=10):
        if not self.is_configured():
            logger.debug("Twitter API未配置")
            return []
        try:
            resp = self.session.get(
                f"{self.API_BASE}/users/{TRUMP_TWITTER_USER_ID}/tweets",
                params={
                    'max_results': min(limit, 100),
                    'tweet.fields': 'created_at,text,referenced_tweets',
                    'exclude': 'replies',
                },
                timeout=REQUEST_TIMEOUT
            )
            if resp.status_code != 200:
                logger.debug(f"Twitter API返回 {resp.status_code}")
                return []
            posts = []
            for tweet in resp.json().get('data', []):
                is_repost = any(
                    r.get('type') == 'retweeted'
                    for r in tweet.get('referenced_tweets', [])
                )
                posts.append({
                    'id': f"tw_{tweet['id']}", 'source': 'twitter',
                    'content': tweet.get('text', ''),
                    'created_at': tweet.get('created_at', ''),
                    'url': f"https://x.com/{TRUMP_TWITTER_USERNAME}/status/{tweet['id']}",
                    'media_urls': [], 'is_repost': is_repost,
                })
            if posts:
                logger.info(f"Twitter API: 获取 {len(posts)} 条")
            return posts
        except Exception as e:
            logger.error(f"Twitter API失败: {e}")
            return []


# ============================================================
# 统一监控器
# ============================================================

class TrumpSocialMonitor:
    """统一监控器：优先Playwright浏览器，降级到HTTP。"""

    def __init__(self):
        # Playwright浏览器方案
        self.pw_truth = PlaywrightTruthSocialMonitor()
        self.pw_twitter = PlaywrightTwitterMonitor()

        # HTTP备用方案
        self.http_truth = HttpTruthSocialMonitor()
        self.http_twitter = HttpTwitterMonitor()

        # 检测Playwright是否可用
        self._playwright_available = self._check_playwright()

    def _check_playwright(self):
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            browser.close()
            pw.stop()
            logger.info("Playwright可用，将优先使用浏览器渲染")
            return True
        except Exception as e:
            logger.info(f"Playwright不可用（{e}），使用HTTP备用方案")
            return False

    def fetch_all_posts(self, limit=20):
        """从所有已配置的数据源获取推文。"""
        all_posts = []

        # Truth Social
        ts_posts = self._fetch_truth_social(limit)
        all_posts.extend(ts_posts)

        # Twitter/X
        tw_posts = self._fetch_twitter(limit)
        all_posts.extend(tw_posts)

        # 按时间倒序
        all_posts.sort(key=lambda p: p.get('created_at', ''), reverse=True)

        ts_count = len([p for p in all_posts if p['source'] == 'truth_social'])
        tw_count = len([p for p in all_posts if p['source'] == 'twitter'])
        logger.info(f"总计获取: {len(all_posts)} 条 (Truth Social: {ts_count}, Twitter: {tw_count})")

        return all_posts

    def _fetch_truth_social(self, limit):
        """获取Truth Social推文，Playwright优先。"""
        if self._playwright_available:
            try:
                posts = self.pw_truth.fetch_posts(limit)
                if posts:
                    return posts
                logger.info("Playwright Truth Social无结果，降级到HTTP")
            except Exception as e:
                logger.warning(f"Playwright Truth Social异常: {e}")

        # HTTP备用
        try:
            return self.http_truth.fetch_posts(limit)
        except Exception as e:
            logger.error(f"HTTP Truth Social异常: {e}")
            return []

    def _fetch_twitter(self, limit):
        """获取Twitter推文，Playwright优先。"""
        if self._playwright_available:
            try:
                posts = self.pw_twitter.fetch_posts(limit)
                if posts:
                    return posts
                logger.info("Playwright Twitter无结果，降级到HTTP")
            except Exception as e:
                logger.warning(f"Playwright Twitter异常: {e}")

        # HTTP备用 (需要API Key)
        try:
            return self.http_twitter.fetch_posts(limit)
        except Exception as e:
            logger.error(f"HTTP Twitter异常: {e}")
            return []
