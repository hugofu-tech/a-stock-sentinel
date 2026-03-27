"""
Trading Signal Generator
Combines LLM analysis with Polymarket market data to produce
actionable trading instructions.

Output signal format:
{
    'signal_id': str,
    'timestamp': str,
    'post': {...},           # Original post
    'analysis': {...},       # LLM analysis
    'market': {...},         # Matched Polymarket market
    'action': 'BUY_YES' | 'BUY_NO' | 'SELL_YES' | 'SELL_NO',
    'confidence': int,       # 0-100
    'suggested_size_usdc': float,
    'current_price': float,
    'urgency': str,
    'reasoning': str,
}
"""

import logging
import time
from datetime import datetime, timezone

from trump_config import (
    MAX_POSITION_SIZE_USDC,
    MIN_CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Generates trading signals from LLM analysis + Polymarket data."""

    def __init__(self, polymarket_client):
        self.polymarket = polymarket_client

    def generate_signal(self, post, analysis):
        """Generate a trading signal for a single analyzed post.

        Args:
            post: Normalized post dict.
            analysis: LLM analysis dict.

        Returns:
            Trading signal dict, or None if not actionable.
        """
        # Check if analysis deems this actionable
        if not analysis.get('is_actionable', False):
            logger.debug(f"Post {post.get('id')} not actionable, skipping")
            return None

        confidence = analysis.get('confidence', 0)
        if confidence < MIN_CONFIDENCE_THRESHOLD:
            logger.debug(
                f"Post {post.get('id')} confidence {confidence}% below "
                f"threshold {MIN_CONFIDENCE_THRESHOLD}%"
            )
            return None

        # Search for relevant Polymarket markets
        keywords = analysis.get('polymarket_keywords', [])
        if not keywords:
            logger.warning(f"No Polymarket keywords for post {post.get('id')}")
            return None

        markets = self.polymarket.search_markets(keywords, limit=5)
        if not markets:
            # Try broader search with just "trump" + first keyword
            broader_keywords = ['trump'] + keywords[:1]
            markets = self.polymarket.search_markets(broader_keywords, limit=5)

        if not markets:
            logger.info(f"No matching Polymarket markets for keywords: {keywords}")
            return None

        # Select the best matching market
        best_market = self._select_best_market(markets, analysis)
        if not best_market:
            return None

        # Determine trading action
        action = self._determine_action(analysis, best_market)

        # Calculate position size based on confidence
        suggested_size = self._calculate_position_size(confidence, best_market)

        # Determine the current price for the action
        if action in ('BUY_YES', 'SELL_NO'):
            current_price = best_market.get('yes_price', 0)
        else:
            current_price = best_market.get('no_price', 0)

        signal = {
            'signal_id': f"sig_{int(time.time())}_{post.get('id', 'unknown')}",
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'post': {
                'id': post.get('id'),
                'source': post.get('source'),
                'content': post.get('content', '')[:500],
                'url': post.get('url', ''),
                'created_at': post.get('created_at', ''),
            },
            'analysis': {
                'topic': analysis.get('topic_category'),
                'impact_score': analysis.get('market_impact_score'),
                'reasoning': analysis.get('impact_reasoning', ''),
            },
            'market': {
                'id': best_market.get('id'),
                'question': best_market.get('question'),
                'url': best_market.get('url'),
                'yes_price': best_market.get('yes_price', 0),
                'no_price': best_market.get('no_price', 0),
                'volume': best_market.get('volume', 0),
            },
            'action': action,
            'confidence': confidence,
            'suggested_size_usdc': suggested_size,
            'current_price': current_price,
            'urgency': analysis.get('urgency', 'watch'),
            'reasoning': self._build_reasoning(post, analysis, best_market, action),
        }

        logger.info(
            f"Signal generated: {action} on '{best_market.get('question', '')[:50]}' "
            f"@ ${current_price:.2f}, confidence={confidence}%, "
            f"size=${suggested_size:.1f} USDC"
        )

        return signal

    def generate_signals_batch(self, analyzed_posts):
        """Generate signals for a batch of analyzed posts.

        Args:
            analyzed_posts: List of {'post': ..., 'analysis': ...} dicts.

        Returns:
            List of trading signal dicts.
        """
        signals = []
        for item in analyzed_posts:
            signal = self.generate_signal(item['post'], item['analysis'])
            if signal:
                signals.append(signal)
        return signals

    def _select_best_market(self, markets, analysis):
        """Select the most relevant market from search results."""
        if not markets:
            return None

        # Prefer markets with:
        # 1. Higher volume (more liquid)
        # 2. Active and not closed
        # 3. Price not too extreme (between 0.05 and 0.95)
        scored = []
        for market in markets:
            score = 0
            yes_price = market.get('yes_price', 0)

            # Liquidity bonus
            volume = market.get('volume', 0)
            if volume > 1_000_000:
                score += 3
            elif volume > 100_000:
                score += 2
            elif volume > 10_000:
                score += 1

            # Price range bonus (not too extreme = more room to move)
            if 0.10 <= yes_price <= 0.90:
                score += 2
            elif 0.05 <= yes_price <= 0.95:
                score += 1

            # Active bonus
            if market.get('active') and not market.get('closed'):
                score += 2

            # Relevance score from search
            score += market.get('_relevance_score', 0)

            scored.append((score, market))

        scored.sort(key=lambda x: -x[0])
        return scored[0][1] if scored else None

    def _determine_action(self, analysis, market):
        """Determine BUY_YES/BUY_NO based on analysis direction."""
        direction = analysis.get('suggested_direction', 'YES').upper()
        yes_price = market.get('yes_price', 0.5)

        if direction == 'YES':
            # LLM thinks this outcome is MORE likely -> BUY YES
            # But if price is already very high, it might be BUY NO
            if yes_price > 0.92:
                return 'BUY_NO'  # Already priced in, contrarian
            return 'BUY_YES'
        else:
            # LLM thinks this outcome is LESS likely -> BUY NO
            if yes_price < 0.08:
                return 'BUY_YES'  # Already priced in, contrarian
            return 'BUY_NO'

    def _calculate_position_size(self, confidence, market):
        """Calculate suggested position size in USDC.

        Higher confidence = larger position.
        More liquid markets = larger position.
        """
        # Base size scales with confidence
        if confidence >= 90:
            base_pct = 1.0
        elif confidence >= 80:
            base_pct = 0.7
        elif confidence >= 70:
            base_pct = 0.5
        else:
            base_pct = 0.3

        # Liquidity adjustment
        volume = market.get('volume', 0)
        if volume < 10_000:
            liquidity_mult = 0.3  # Low liquidity, reduce size
        elif volume < 100_000:
            liquidity_mult = 0.6
        else:
            liquidity_mult = 1.0

        size = MAX_POSITION_SIZE_USDC * base_pct * liquidity_mult
        return round(max(1.0, size), 2)

    @staticmethod
    def _build_reasoning(post, analysis, market, action):
        """Build human-readable reasoning for the signal."""
        source_name = "Truth Social" if post.get('source') == 'truth_social' else "X/Twitter"
        impact = analysis.get('market_impact_score', 0)
        topic = analysis.get('topic_category', 'unknown')
        llm_reasoning = analysis.get('impact_reasoning', '')

        parts = [
            f"Trump posted on {source_name} about {topic} (impact: {impact}/10).",
            llm_reasoning,
            f"Matched market: \"{market.get('question', '')}\"",
            f"Action: {action} @ current price ${market.get('yes_price', 0):.2f} YES / "
            f"${market.get('no_price', 0):.2f} NO.",
        ]

        return " ".join(filter(None, parts))
