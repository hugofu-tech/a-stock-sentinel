"""
Polymarket客户端
通过Gamma API获取预测市场数据。

第一阶段：只读，搜索市场和获取价格。
第二阶段：通过CLOB API下单（py-clob-client）。

API地址：https://gamma-api.polymarket.com
市场为YES/NO二元预测市场，价格范围$0.01-$0.99代表概率。
"""

import json
import logging

import requests

from trump_config import POLYMARKET_GAMMA_API

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
# 每次API请求最大条数
PAGE_SIZE = 100
# 搜索市场时最多拉取的页数
MAX_PAGES = 5


class PolymarketClient:
    """Polymarket Gamma API客户端。"""

    def __init__(self):
        self.base_url = POLYMARKET_GAMMA_API
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'TrumpSentinel/1.0',
        })
        # 缓存，避免重复请求
        self._market_cache = []
        self._event_cache = []

    def search_markets(self, keywords, limit=10, active_only=True):
        """搜索Polymarket匹配关键词的市场。

        策略：
        1. 先尝试从events端点搜索（包含更多结构化数据）
        2. 再从markets端点分页拉取并过滤
        3. 合并去重后按相关度+成交量排序

        Args:
            keywords: 搜索词列表或单个字符串。
            limit: 返回的最大市场数。
            active_only: 是否只返回活跃市场。

        Returns:
            标准化的市场字典列表。
        """
        if isinstance(keywords, list):
            query = " ".join(keywords)
        else:
            query = keywords

        query_terms = query.lower().split()

        try:
            # 1. 从events搜索（events包含子市场，覆盖面更广）
            event_markets = self._search_via_events(query_terms)

            # 2. 从markets端点分页搜索
            direct_markets = self._search_via_markets(query_terms, active_only)

            # 3. 合并去重
            seen_ids = set()
            all_matched = []

            for m in event_markets + direct_markets:
                mid = m.get('id') or m.get('slug')
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    all_matched.append(m)

            # 4. 按相关度+成交量排序
            all_matched.sort(key=lambda m: (
                -float(m.get('_relevance_score', 0)),
                -float(m.get('volume', 0) or 0)
            ))

            results = [self._normalize_market(m) if not m.get('_normalized') else m
                        for m in all_matched[:limit]]

            logger.info(f"Polymarket搜索 '{query}': 找到 {len(results)} 个市场 "
                        f"(events: {len(event_markets)}, markets: {len(direct_markets)})")
            return results

        except Exception as e:
            logger.error(f"Polymarket搜索失败: {e}")
            return []

    def _search_via_events(self, query_terms):
        """通过events端点搜索，提取子市场。"""
        matched_markets = []

        try:
            # 拉取活跃事件
            events = self._fetch_events()

            for event in events:
                title = (event.get('title', '') or '').lower()
                desc = (event.get('description', '') or '').lower()
                searchable = title + ' ' + desc

                event_score = sum(1 for t in query_terms if t in searchable)
                if event_score == 0:
                    continue

                # 从事件中提取子市场
                for market in event.get('markets', []):
                    q = (market.get('question', '') or '').lower()
                    d = (market.get('description', '') or '').lower()
                    market_text = q + ' ' + d

                    market_score = sum(1 for t in query_terms if t in market_text)
                    # 事件匹配的市场也算相关
                    total_score = max(event_score, market_score) + min(event_score, market_score) * 0.5

                    if total_score > 0:
                        market['_relevance_score'] = total_score
                        matched_markets.append(market)

        except Exception as e:
            logger.error(f"Events搜索失败: {e}")

        return matched_markets

    def _search_via_markets(self, query_terms, active_only):
        """通过markets端点分页搜索。"""
        matched = []

        try:
            all_markets = self._fetch_markets(active_only)

            for market in all_markets:
                question = (market.get('question', '') or '').lower()
                description = (market.get('description', '') or '').lower()
                searchable = question + ' ' + description

                score = sum(1 for term in query_terms if term in searchable)
                if score > 0:
                    market['_relevance_score'] = score
                    matched.append(market)

        except Exception as e:
            logger.error(f"Markets搜索失败: {e}")

        return matched

    def _fetch_events(self):
        """拉取所有活跃事件（带缓存）。"""
        if self._event_cache:
            return self._event_cache

        all_events = []
        offset = 0

        for _ in range(MAX_PAGES):
            try:
                resp = self.session.get(
                    f"{self.base_url}/events",
                    params={
                        'limit': PAGE_SIZE,
                        'active': 'true',
                        'closed': 'false',
                        'offset': offset,
                    },
                    timeout=REQUEST_TIMEOUT
                )
                if resp.status_code != 200:
                    break

                batch = resp.json()
                if not batch:
                    break

                all_events.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE

            except Exception:
                break

        self._event_cache = all_events
        logger.debug(f"拉取了 {len(all_events)} 个事件")
        return all_events

    def _fetch_markets(self, active_only):
        """分页拉取市场列表（带缓存）。"""
        if self._market_cache:
            return self._market_cache

        all_markets = []
        offset = 0

        for _ in range(MAX_PAGES):
            try:
                params = {
                    'limit': PAGE_SIZE,
                    'closed': 'false',
                    'offset': offset,
                }
                if active_only:
                    params['active'] = 'true'

                resp = self.session.get(
                    f"{self.base_url}/markets",
                    params=params,
                    timeout=REQUEST_TIMEOUT
                )
                if resp.status_code != 200:
                    break

                batch = resp.json()
                if not batch:
                    break

                all_markets.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE

            except Exception:
                break

        self._market_cache = all_markets
        logger.debug(f"拉取了 {len(all_markets)} 个市场")
        return all_markets

    def clear_cache(self):
        """清除缓存，下次搜索将重新拉取数据。"""
        self._market_cache = []
        self._event_cache = []

    def get_market(self, market_id):
        """获取单个市场详情。"""
        try:
            url = f"{self.base_url}/markets/{market_id}"
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)

            if resp.status_code != 200:
                logger.warning(f"Polymarket市场 {market_id} 返回 {resp.status_code}")
                return None

            return self._normalize_market(resp.json())

        except Exception as e:
            logger.error(f"获取市场失败: {e}")
            return None

    def get_market_price(self, market_id):
        """获取市场当前YES/NO价格。"""
        market = self.get_market(market_id)
        if market:
            return {
                'yes_price': market.get('yes_price', 0),
                'no_price': market.get('no_price', 0),
            }
        return None

    @staticmethod
    def _normalize_market(market):
        """将原始市场数据标准化为统一格式。"""
        # 从tokens字段提取价格
        tokens = market.get('tokens', [])
        yes_price = 0.0
        no_price = 0.0
        for token in tokens:
            outcome = (token.get('outcome', '') or '').lower()
            price = float(token.get('price', 0) or 0)
            if outcome == 'yes':
                yes_price = price
            elif outcome == 'no':
                no_price = price

        # 备用：从outcomePrices字段提取
        if yes_price == 0 and no_price == 0:
            outcome_prices = market.get('outcomePrices', '')
            if outcome_prices:
                try:
                    prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                    if len(prices) >= 2:
                        yes_price = float(prices[0])
                        no_price = float(prices[1])
                except (json.JSONDecodeError, ValueError, IndexError):
                    pass

        condition_id = market.get('conditionId') or market.get('condition_id', '')
        slug = market.get('slug', '')

        result = {
            'id': condition_id,
            'slug': slug,
            'question': market.get('question', ''),
            'description': market.get('description', ''),
            'yes_price': yes_price,
            'no_price': no_price,
            'volume': float(market.get('volume', 0) or 0),
            'volume_24h': float(market.get('volume24hr', 0) or 0),
            'liquidity': float(market.get('liquidity', 0) or 0),
            'end_date': market.get('endDate', ''),
            'active': market.get('active', False),
            'closed': market.get('closed', False),
            'url': f"https://polymarket.com/market/{slug}" if slug else '',
            '_normalized': True,
            '_relevance_score': market.get('_relevance_score', 0),
        }
        return result
