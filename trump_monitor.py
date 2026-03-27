"""
Trump Social Media Monitor
Polls Truth Social and X (Twitter) for new posts from Trump.

Data sources:
- Truth Social: RSS/web scraping (no official API)
- X/Twitter: Twitter API v2 (requires Bearer Token)

Each source returns normalized post dicts:
{
    'id': str,
    'source': 'truth_social' | 'twitter',
    'content': str,
    'created_at': str (ISO format),
    'url': str,
    'media_urls': list[str],
    'is_repost': bool
}
"""

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

# Request timeout
REQUEST_TIMEOUT = 15


class TruthSocialMonitor:
    """Monitor Trump's Truth Social account via RSS and web scraping."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36'
        })
        self.rss_url = f"{TRUTH_SOCIAL_BASE_URL}/@{TRUTH_SOCIAL_USERNAME}/rss"

    def fetch_posts(self, limit=20):
        """Fetch recent Truth Social posts via RSS feed.

        Falls back to profile page scraping if RSS is unavailable.
        """
        posts = self._fetch_via_rss(limit)
        if posts:
            return posts

        logger.info("RSS unavailable, falling back to profile scraping")
        return self._fetch_via_scrape(limit)

    def _fetch_via_rss(self, limit):
        """Try fetching posts from Truth Social RSS feed."""
        try:
            resp = self.session.get(self.rss_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.warning(f"Truth Social RSS returned {resp.status_code}")
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

                posts.append({
                    'id': f"ts_{self._extract_id(guid)}",
                    'source': 'truth_social',
                    'content': content,
                    'created_at': pub_date,
                    'url': link,
                    'media_urls': self._extract_media_urls(description),
                    'is_repost': False,
                })

            logger.info(f"Truth Social RSS: fetched {len(posts)} posts")
            return posts

        except Exception as e:
            logger.error(f"Truth Social RSS fetch failed: {e}")
            return []

    def _fetch_via_scrape(self, limit):
        """Fallback: scrape Truth Social profile page."""
        try:
            url = f"{TRUTH_SOCIAL_BASE_URL}/@{TRUTH_SOCIAL_USERNAME}"
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.warning(f"Truth Social scrape returned {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, 'html.parser')
            posts = []

            # Look for status content blocks
            status_elements = soup.find_all('div', class_=re.compile(r'status'))
            for elem in status_elements[:limit]:
                content_elem = elem.find('div', class_=re.compile(r'content|text'))
                if not content_elem:
                    continue

                content = content_elem.get_text(strip=True)
                if not content:
                    continue

                # Try to extract post link/ID
                link_elem = elem.find('a', href=re.compile(r'/@\w+/\d+'))
                post_url = link_elem['href'] if link_elem else ''
                post_id = self._extract_id(post_url)

                posts.append({
                    'id': f"ts_{post_id or hash(content)}",
                    'source': 'truth_social',
                    'content': content,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'url': f"{TRUTH_SOCIAL_BASE_URL}{post_url}" if post_url else '',
                    'media_urls': [],
                    'is_repost': False,
                })

            logger.info(f"Truth Social scrape: fetched {len(posts)} posts")
            return posts

        except Exception as e:
            logger.error(f"Truth Social scrape failed: {e}")
            return []

    @staticmethod
    def _clean_html(html_text):
        """Strip HTML tags from text."""
        if not html_text:
            return ''
        soup = BeautifulSoup(html_text, 'html.parser')
        return soup.get_text(strip=True)

    @staticmethod
    def _extract_id(url_or_guid):
        """Extract numeric ID from URL or GUID."""
        if not url_or_guid:
            return str(int(time.time() * 1000))
        match = re.search(r'/(\d+)', url_or_guid)
        return match.group(1) if match else str(hash(url_or_guid))

    @staticmethod
    def _extract_media_urls(html_text):
        """Extract image/video URLs from HTML content."""
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
    """Monitor Trump's X/Twitter account via Twitter API v2."""

    API_BASE = "https://api.twitter.com/2"

    def __init__(self):
        self.bearer_token = TWITTER_BEARER_TOKEN
        self.session = requests.Session()
        if self.bearer_token:
            self.session.headers.update({
                'Authorization': f'Bearer {self.bearer_token}'
            })

    def is_configured(self):
        """Check if Twitter API credentials are available."""
        return bool(self.bearer_token)

    def fetch_posts(self, limit=10):
        """Fetch recent tweets from Trump's account.

        Uses Twitter API v2 user timeline endpoint.
        """
        if not self.is_configured():
            logger.warning("Twitter API not configured (no TWITTER_BEARER_TOKEN)")
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
                logger.warning("Twitter API rate limited")
                return []

            if resp.status_code != 200:
                logger.warning(f"Twitter API returned {resp.status_code}: {resp.text[:200]}")
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

            logger.info(f"Twitter API: fetched {len(posts)} tweets")
            return posts

        except Exception as e:
            logger.error(f"Twitter API fetch failed: {e}")
            return []


class TrumpSocialMonitor:
    """Unified monitor for all Trump social media accounts."""

    def __init__(self):
        self.truth_social = TruthSocialMonitor()
        self.twitter = TwitterMonitor()

    def fetch_all_posts(self, limit=20):
        """Fetch posts from all configured sources.

        Returns:
            List of normalized post dicts, sorted by recency.
        """
        all_posts = []

        # Truth Social
        try:
            ts_posts = self.truth_social.fetch_posts(limit)
            all_posts.extend(ts_posts)
        except Exception as e:
            logger.error(f"Truth Social monitor error: {e}")

        # Twitter/X
        try:
            tw_posts = self.twitter.fetch_posts(limit)
            all_posts.extend(tw_posts)
        except Exception as e:
            logger.error(f"Twitter monitor error: {e}")

        # Sort by created_at (newest first)
        all_posts.sort(key=lambda p: p.get('created_at', ''), reverse=True)

        logger.info(f"Total fetched: {len(all_posts)} posts "
                     f"(Truth Social: {len([p for p in all_posts if p['source'] == 'truth_social'])}, "
                     f"Twitter: {len([p for p in all_posts if p['source'] == 'twitter'])})")

        return all_posts
