"""
特朗普社交媒体监控器
轮询Truth Social和X(Twitter)获取特朗普最新发帖。

数据源策略：
- Truth Social：官方API返回403，使用多层备用方案
  1. RSS订阅
  2. 第三方聚合API（如RapidAPI的Truth Social端点）
  3. 公开的Mastodon兼容API
  4. 直接网页抓取
- X/Twitter：Twitter API v2（需Bearer Token）

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
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


class TruthSocialMonitor:
    """通过多种方式监控特朗普的Truth Social账号。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self.rss_url = f"{TRUTH_SOCIAL_BASE_URL}/@{TRUTH_SOCIAL_USERNAME}/rss"
        self.account_id = None  # 延迟获取

    def fetch_posts(self, limit=20):
        """按优先级尝试多种方式获取推文。"""
        # 方案1：RSS
        posts = self._fetch_via_rss(limit)
        if posts:
            return posts

        # 方案2：Mastodon兼容API（Truth Social基于Mastodon）
        posts = self._fetch_via_mastodon_api(limit)
        if posts:
            return posts

        # 方案3：公开时间线API
        posts = self._fetch_via_public_api(limit)
        if posts:
            return posts

        # 方案4：直接网页抓取（含JS渲染的内容）
        posts = self._fetch_via_scrape(limit)
        if posts:
            return posts

        logger.warning("所有Truth Social数据源均失败")
        return []

    def _fetch_via_rss(self, limit):
        """通过RSS订阅获取。"""
        try:
            resp = self.session.get(self.rss_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.debug(f"Truth Social RSS 返回 {resp.status_code}")
                return []

            root = ET.fromstring(resp.text)
            posts = []

            for item in root.findall('.//item')[:limit]:
                title = item.findtext('title', '')
                description = item.findtext('description', '')
                link = item.findtext('link', '')
                pub_date = item.findtext('pubDate', '')
                guid = item.findtext('guid', link)

                content = self._clean_html(description or title)
                if not content:
                    continue

                posts.append(self._make_post(
                    post_id=self._extract_id(guid),
                    content=content,
                    created_at=pub_date,
                    url=link,
                    media_urls=self._extract_media_urls(description),
                ))

            logger.info(f"Truth Social RSS: 获取 {len(posts)} 条")
            return posts
        except Exception as e:
            logger.debug(f"Truth Social RSS失败: {e}")
            return []

    def _fetch_via_mastodon_api(self, limit):
        """通过Mastodon兼容API获取（Truth Social基于Mastodon分支）。"""
        try:
            # 先获取账号ID
            if not self.account_id:
                lookup_url = f"{TRUTH_SOCIAL_BASE_URL}/api/v1/accounts/lookup"
                resp = self.session.get(
                    lookup_url,
                    params={'acct': TRUTH_SOCIAL_USERNAME},
                    timeout=REQUEST_TIMEOUT
                )
                if resp.status_code == 200:
                    self.account_id = resp.json().get('id')
                else:
                    logger.debug(f"Mastodon账号查询返回 {resp.status_code}")
                    return []

            if not self.account_id:
                return []

            # 获取推文
            statuses_url = f"{TRUTH_SOCIAL_BASE_URL}/api/v1/accounts/{self.account_id}/statuses"
            resp = self.session.get(
                statuses_url,
                params={
                    'limit': limit,
                    'exclude_replies': 'true',
                    'exclude_reblogs': 'false',
                },
                timeout=REQUEST_TIMEOUT
            )

            if resp.status_code != 200:
                logger.debug(f"Mastodon API返回 {resp.status_code}")
                return []

            statuses = resp.json()
            posts = []

            for status in statuses:
                content = self._clean_html(status.get('content', ''))
                if not content:
                    continue

                media_urls = [
                    m.get('url', '')
                    for m in status.get('media_attachments', [])
                    if m.get('url')
                ]

                posts.append(self._make_post(
                    post_id=str(status.get('id', '')),
                    content=content,
                    created_at=status.get('created_at', ''),
                    url=status.get('url', ''),
                    media_urls=media_urls,
                    is_repost=status.get('reblog') is not None,
                ))

            logger.info(f"Truth Social Mastodon API: 获取 {len(posts)} 条")
            return posts

        except Exception as e:
            logger.debug(f"Mastodon API失败: {e}")
            return []

    def _fetch_via_public_api(self, limit):
        """通过Truth Social公开API获取。"""
        try:
            # Truth Social有时开放公开时间线
            url = f"{TRUTH_SOCIAL_BASE_URL}/api/v1/truth/trending/truths"
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)

            if resp.status_code != 200:
                logger.debug(f"Truth Social公开API返回 {resp.status_code}")
                return []

            truths = resp.json()
            posts = []

            for truth in truths:
                # 只筛选特朗普的推文
                account = truth.get('account', {})
                username = account.get('username', '') or account.get('acct', '')
                if username.lower() != TRUTH_SOCIAL_USERNAME.lower():
                    continue

                content = self._clean_html(truth.get('content', ''))
                if not content:
                    continue

                posts.append(self._make_post(
                    post_id=str(truth.get('id', '')),
                    content=content,
                    created_at=truth.get('created_at', ''),
                    url=truth.get('url', ''),
                ))

            logger.info(f"Truth Social公开API: 获取 {len(posts)} 条")
            return posts[:limit]

        except Exception as e:
            logger.debug(f"Truth Social公开API失败: {e}")
            return []

    def _fetch_via_scrape(self, limit):
        """直接抓取Truth Social页面（最后手段）。"""
        try:
            url = f"{TRUTH_SOCIAL_BASE_URL}/@{TRUTH_SOCIAL_USERNAME}"
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.debug(f"Truth Social页面抓取返回 {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, 'html.parser')
            posts = []

            # 尝试从页面JSON数据中提取（SPA通常会内嵌初始数据）
            scripts = soup.find_all('script', type='application/json')
            for script in scripts:
                try:
                    data = json.loads(script.string or '{}')
                    posts.extend(self._extract_posts_from_json(data, limit))
                except (json.JSONDecodeError, TypeError):
                    continue

            if posts:
                logger.info(f"Truth Social JSON提取: 获取 {len(posts)} 条")
                return posts[:limit]

            # 回退到DOM解析
            status_elements = soup.find_all('div', class_=re.compile(r'status'))
            for elem in status_elements[:limit]:
                content_elem = elem.find('div', class_=re.compile(r'content|text'))
                if not content_elem:
                    continue

                content = content_elem.get_text(strip=True)
                if not content:
                    continue

                link_elem = elem.find('a', href=re.compile(r'/@\w+/\d+'))
                post_url = link_elem['href'] if link_elem else ''
                post_id = self._extract_id(post_url)

                posts.append(self._make_post(
                    post_id=post_id or str(hash(content)),
                    content=content,
                    url=f"{TRUTH_SOCIAL_BASE_URL}{post_url}" if post_url else '',
                ))

            logger.info(f"Truth Social DOM抓取: 获取 {len(posts)} 条")
            return posts

        except Exception as e:
            logger.debug(f"Truth Social页面抓取失败: {e}")
            return []

    def _extract_posts_from_json(self, data, limit):
        """从页面内嵌JSON中递归提取推文数据。"""
        posts = []
        if isinstance(data, dict):
            # 找到包含content和account的对象
            if 'content' in data and 'account' in data:
                account = data.get('account', {})
                username = account.get('username', '') or account.get('acct', '')
                if username.lower() == TRUTH_SOCIAL_USERNAME.lower():
                    content = self._clean_html(data.get('content', ''))
                    if content:
                        posts.append(self._make_post(
                            post_id=str(data.get('id', hash(content))),
                            content=content,
                            created_at=data.get('created_at', ''),
                            url=data.get('url', ''),
                        ))
            # 递归搜索
            for value in data.values():
                if isinstance(value, (dict, list)):
                    posts.extend(self._extract_posts_from_json(value, limit))
                    if len(posts) >= limit:
                        break
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    posts.extend(self._extract_posts_from_json(item, limit))
                    if len(posts) >= limit:
                        break
        return posts

    @staticmethod
    def _make_post(post_id, content, created_at=None, url='',
                   media_urls=None, is_repost=False):
        """构造标准推文字典。"""
        return {
            'id': f"ts_{post_id}",
            'source': 'truth_social',
            'content': content,
            'created_at': created_at or datetime.now(timezone.utc).isoformat(),
            'url': url,
            'media_urls': media_urls or [],
            'is_repost': is_repost,
        }

    @staticmethod
    def _clean_html(html_text):
        """清除HTML标签。"""
        if not html_text:
            return ''
        soup = BeautifulSoup(html_text, 'html.parser')
        return soup.get_text(strip=True)

    @staticmethod
    def _extract_id(url_or_guid):
        """从URL或GUID中提取数字ID。"""
        if not url_or_guid:
            return str(int(time.time() * 1000))
        match = re.search(r'/(\d+)', url_or_guid)
        return match.group(1) if match else str(hash(url_or_guid))

    @staticmethod
    def _extract_media_urls(html_text):
        """从HTML中提取图片/视频URL。"""
        if not html_text:
            return []
        soup = BeautifulSoup(html_text, 'html.parser')
        urls = []
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src and not src.endswith('.svg'):
                urls.append(src)
        for video in soup.find_all('video'):
            src = video.get('src', '')
            if src:
                urls.append(src)
        return urls


class TwitterMonitor:
    """通过Twitter API v2监控特朗普的X账号。"""

    API_BASE = "https://api.twitter.com/2"

    def __init__(self):
        self.bearer_token = TWITTER_BEARER_TOKEN
        self.session = requests.Session()
        if self.bearer_token:
            self.session.headers.update({
                'Authorization': f'Bearer {self.bearer_token}'
            })

    def is_configured(self):
        """检查Twitter API是否已配置。"""
        return bool(self.bearer_token)

    def fetch_posts(self, limit=10):
        """获取特朗普最近的推文。"""
        if not self.is_configured():
            logger.warning("Twitter API未配置（缺少TWITTER_BEARER_TOKEN）")
            return []

        try:
            url = f"{self.API_BASE}/users/{TRUMP_TWITTER_USER_ID}/tweets"
            params = {
                'max_results': min(limit, 100),
                'tweet.fields': 'created_at,text,referenced_tweets,attachments',
                'exclude': 'replies',
            }

            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 429:
                logger.warning("Twitter API被限速")
                return []

            if resp.status_code != 200:
                logger.warning(f"Twitter API返回 {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            tweets = data.get('data', [])
            posts = []

            for tweet in tweets:
                is_repost = any(
                    ref.get('type') == 'retweeted'
                    for ref in tweet.get('referenced_tweets', [])
                )

                posts.append({
                    'id': f"tw_{tweet['id']}",
                    'source': 'twitter',
                    'content': tweet.get('text', ''),
                    'created_at': tweet.get('created_at', ''),
                    'url': f"https://x.com/{TRUMP_TWITTER_USERNAME}/status/{tweet['id']}",
                    'media_urls': [],
                    'is_repost': is_repost,
                })

            logger.info(f"Twitter API: 获取 {len(posts)} 条推文")
            return posts

        except Exception as e:
            logger.error(f"Twitter API获取失败: {e}")
            return []


class TrumpSocialMonitor:
    """统一监控器：聚合所有特朗普社交媒体源。"""

    def __init__(self):
        self.truth_social = TruthSocialMonitor()
        self.twitter = TwitterMonitor()

    def fetch_all_posts(self, limit=20):
        """从所有已配置的数据源获取推文。

        Returns:
            标准化的推文字典列表，按时间倒序排列。
        """
        all_posts = []

        # Truth Social
        try:
            ts_posts = self.truth_social.fetch_posts(limit)
            all_posts.extend(ts_posts)
        except Exception as e:
            logger.error(f"Truth Social监控错误: {e}")

        # Twitter/X
        try:
            tw_posts = self.twitter.fetch_posts(limit)
            all_posts.extend(tw_posts)
        except Exception as e:
            logger.error(f"Twitter监控错误: {e}")

        # 按时间倒序
        all_posts.sort(key=lambda p: p.get('created_at', ''), reverse=True)

        ts_count = len([p for p in all_posts if p['source'] == 'truth_social'])
        tw_count = len([p for p in all_posts if p['source'] == 'twitter'])
        logger.info(f"总计获取: {len(all_posts)} 条 (Truth Social: {ts_count}, Twitter: {tw_count})")

        return all_posts
