"""
Polymarket Client
Fetches market data from Polymarket's Gamma API.

Phase 1: Read-only market search and price fetching.
Phase 2: Order placement via CLOB API (py-clob-client).

Polymarket Gamma API docs: https://gamma-api.polymarket.com
Markets are prediction markets with YES/NO outcomes.
Prices range from $0.01 to $0.99 representing probability.
"""

import logging
from urllib.parse import quote

import requests

from trump_config import POLYMARKET_GAMMA_API

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


class PolymarketClient:
    """Client for Polymarket Gamma API (market data)."""

    def __init__(self):
        self.base_url = POLYMARKET_GAMMA_API
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'TrumpSentinel/1.0',
        })

    def search_markets(self, keywords, limit=10, active_only=True):
        """Search Polymarket for markets matching keywords.

        Args:
            keywords: List of search terms or a single string.
            limit: Max markets to return.
            active_only: Only return active/open markets.

        Returns:
            List of market dicts with key fields normalized.
        """
        if isinstance(keywords, list):
            query = " ".join(keywords)
        else:
            query = keywords

        try:
            url = f"{self.base_url}/markets"
            params = {
                'limit': limit,
                'active': str(active_only).lower(),
                'closed': 'false',
            }

            # Use text_query for search if the API supports it
            # The Gamma API uses a query parameter for full-text search
            params['limit'] = limit

            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)

            if resp.status_code != 200:
                logger.warning(f"Polymarket API returned {resp.status_code}")
                return []

            all_markets = resp.json()

            # Filter by keyword relevance (client-side filtering)
            query_lower = query.lower()
            query_terms = query_lower.split()

            matched = []
            for market in all_markets:
                question = (market.get('question', '') or '').lower()
                description = (market.get('description', '') or '').lower()
                searchable = question + ' ' + description

                # Score by number of matching terms
                score = sum(1 for term in query_terms if term in searchable)
                if score > 0:
                    market['_relevance_score'] = score
                    matched.append(market)

            # Sort by relevance then by volume
            matched.sort(key=lambda m: (
                -m.get('_relevance_score', 0),
                -float(m.get('volume', 0) or 0)
            ))

            results = [self._normalize_market(m) for m in matched[:limit]]
            logger.info(f"Polymarket search '{query}': found {len(results)} markets")
            return results

        except Exception as e:
            logger.error(f"Polymarket search failed: {e}")
            return []

    def search_events(self, keywords, limit=5):
        """Search Polymarket events (which contain multiple markets).

        Args:
            keywords: Search terms.
            limit: Max events to return.

        Returns:
            List of event dicts.
        """
        if isinstance(keywords, list):
            query = " ".join(keywords)
        else:
            query = keywords

        try:
            url = f"{self.base_url}/events"
            params = {
                'limit': 50,
                'active': 'true',
                'closed': 'false',
            }

            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)

            if resp.status_code != 200:
                logger.warning(f"Polymarket events API returned {resp.status_code}")
                return []

            all_events = resp.json()
            query_lower = query.lower()
            query_terms = query_lower.split()

            matched = []
            for event in all_events:
                title = (event.get('title', '') or '').lower()
                description = (event.get('description', '') or '').lower()
                searchable = title + ' ' + description

                score = sum(1 for term in query_terms if term in searchable)
                if score > 0:
                    event['_relevance_score'] = score
                    matched.append(event)

            matched.sort(key=lambda e: -e.get('_relevance_score', 0))

            results = []
            for event in matched[:limit]:
                normalized = {
                    'id': event.get('id'),
                    'title': event.get('title', ''),
                    'description': event.get('description', ''),
                    'markets': [
                        self._normalize_market(m)
                        for m in event.get('markets', [])
                    ],
                    'url': f"https://polymarket.com/event/{event.get('slug', event.get('id', ''))}",
                }
                results.append(normalized)

            logger.info(f"Polymarket event search '{query}': found {len(results)} events")
            return results

        except Exception as e:
            logger.error(f"Polymarket event search failed: {e}")
            return []

    def get_market(self, market_id):
        """Get detailed info for a specific market.

        Args:
            market_id: Polymarket condition_id or market slug.

        Returns:
            Normalized market dict or None.
        """
        try:
            url = f"{self.base_url}/markets/{market_id}"
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)

            if resp.status_code != 200:
                logger.warning(f"Polymarket market {market_id} returned {resp.status_code}")
                return None

            return self._normalize_market(resp.json())

        except Exception as e:
            logger.error(f"Polymarket get_market failed: {e}")
            return None

    def get_market_price(self, market_id):
        """Get current YES/NO prices for a market.

        Returns:
            Dict with 'yes_price' and 'no_price' (0.0-1.0), or None.
        """
        market = self.get_market(market_id)
        if market:
            return {
                'yes_price': market.get('yes_price', 0),
                'no_price': market.get('no_price', 0),
            }
        return None

    @staticmethod
    def _normalize_market(market):
        """Normalize a raw market object to a consistent format."""
        # Extract token prices
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

        # Fallback: try outcomePrices field
        if yes_price == 0 and no_price == 0:
            outcome_prices = market.get('outcomePrices', '')
            if outcome_prices:
                try:
                    import json
                    prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                    if len(prices) >= 2:
                        yes_price = float(prices[0])
                        no_price = float(prices[1])
                except (json.JSONDecodeError, ValueError, IndexError):
                    pass

        condition_id = market.get('conditionId') or market.get('condition_id', '')
        slug = market.get('slug', '')

        return {
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
        }
