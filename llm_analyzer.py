"""
LLM-based Post Analyzer
Uses Claude API to analyze Trump's social media posts and determine:
1. Topic classification
2. Market impact assessment
3. Relevant Polymarket keywords
4. Suggested trading direction and confidence

Returns structured analysis as a dict.
"""

import json
import logging
from anthropic import Anthropic

from trump_config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, TOPIC_CATEGORIES

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert political analyst and prediction market trader.
Your job is to analyze posts from Donald Trump's social media accounts and determine
if they have market-moving potential for prediction markets (specifically Polymarket).

You must return a JSON object with the following fields:
- topic_category: one of the predefined categories (see list below)
- market_impact_score: integer 1-10 (1=no impact, 10=massive market mover)
- impact_reasoning: brief explanation of why this post matters (or doesn't)
- polymarket_keywords: list of 2-5 search terms to find relevant Polymarket markets
- suggested_direction: "YES" or "NO" (which outcome becomes more likely due to this post)
- direction_target: what the YES/NO refers to (e.g., "Trump wins 2024", "Tariffs on China")
- confidence: integer 0-100 (how confident you are in the trading signal)
- urgency: "immediate" | "watch" | "low"
- is_actionable: boolean (true if this post warrants a trading signal)

Topic categories: {categories}

Rules:
- Only mark is_actionable=true if market_impact_score >= 5
- Posts that are generic rallying, personal attacks without policy, or reposts of news
  typically have low impact (1-3)
- Posts announcing specific policy actions, executive orders, personnel changes, or
  negotiations have high impact (6-10)
- Consider the TIMING - a post during market hours has higher urgency
- If the post is ambiguous, err on the side of caution (lower confidence)
- For confidence: 80-100 = very clear signal, 60-79 = moderate, <60 = uncertain

Return ONLY valid JSON, no other text."""

USER_PROMPT_TEMPLATE = """Analyze this social media post from Donald Trump:

Source: {source}
Posted at: {created_at}
URL: {url}

Content:
---
{content}
---

Return your analysis as JSON."""


class LLMAnalyzer:
    """Analyzes Trump's posts using Claude API for market impact assessment."""

    def __init__(self):
        self.client = None
        if ANTHROPIC_API_KEY:
            self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = ANTHROPIC_MODEL

    def is_configured(self):
        """Check if Claude API is available."""
        return self.client is not None

    def analyze_post(self, post):
        """Analyze a single post for market impact.

        Args:
            post: Normalized post dict from trump_monitor.

        Returns:
            Analysis dict with trading signals, or None on failure.
        """
        if not self.is_configured():
            logger.warning("Claude API not configured (no ANTHROPIC_API_KEY)")
            return self._fallback_analysis(post)

        try:
            system = SYSTEM_PROMPT.format(categories=", ".join(TOPIC_CATEGORIES))
            user_msg = USER_PROMPT_TEMPLATE.format(
                source=post.get('source', 'unknown'),
                created_at=post.get('created_at', 'unknown'),
                url=post.get('url', ''),
                content=post.get('content', ''),
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )

            # Extract text content
            text = response.content[0].text.strip()

            # Parse JSON from response (handle markdown code blocks)
            if text.startswith('```'):
                text = text.split('\n', 1)[1]
                text = text.rsplit('```', 1)[0]
            text = text.strip()

            analysis = json.loads(text)

            # Validate required fields
            required_fields = [
                'topic_category', 'market_impact_score', 'polymarket_keywords',
                'suggested_direction', 'confidence', 'is_actionable'
            ]
            for field in required_fields:
                if field not in analysis:
                    logger.warning(f"Missing field in LLM response: {field}")
                    analysis[field] = self._default_value(field)

            # Attach original post reference
            analysis['post_id'] = post.get('id')
            analysis['post_source'] = post.get('source')

            logger.info(
                f"Analysis complete: impact={analysis['market_impact_score']}, "
                f"actionable={analysis['is_actionable']}, "
                f"confidence={analysis.get('confidence', 0)}%"
            )

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return self._fallback_analysis(post)
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return self._fallback_analysis(post)

    def analyze_batch(self, posts):
        """Analyze multiple posts, returning list of analyses.

        Only returns analyses for actionable posts.
        """
        results = []
        for post in posts:
            analysis = self.analyze_post(post)
            if analysis:
                results.append({
                    'post': post,
                    'analysis': analysis,
                })
        return results

    def _fallback_analysis(self, post):
        """基于规则的降级分析（当LLM不可用时）。"""
        content = post.get('content', '').lower()

        # 主题关键词映射
        topic_keywords = {
            'tariffs_trade': ['tariff', 'trade', 'china', 'import', 'export', 'duty', 'wto', 'trade deal', 'trade war'],
            'crypto_digital': ['bitcoin', 'crypto', 'btc', 'digital currency', 'cbdc', 'blockchain', 'reserve'],
            'foreign_policy': ['russia', 'ukraine', 'nato', 'sanctions', 'war', 'peace', 'iran', 'north korea', 'israel', 'gaza'],
            'election_politics': ['election', 'vote', 'ballot', 'campaign', 'debate', 'nominee', 'running mate'],
            'economy_fiscal': ['tax', 'fed', 'interest rate', 'inflation', 'debt', 'deficit', 'spending', 'gdp'],
            'regulation_policy': ['executive order', 'regulation', 'ban', 'signing', 'signed'],
            'personnel': ['fired', 'appointed', 'hired', 'cabinet', 'secretary', 'resign', 'replaced', 'nomination'],
            'legal_judicial': ['court', 'judge', 'trial', 'pardon', 'indictment', 'supreme court', 'ruling'],
            'military_defense': ['military', 'troops', 'deploy', 'strike', 'missile', 'defense'],
            'tech_social_media': ['tiktok', 'big tech', 'facebook', 'google', 'section 230', 'ai'],
        }

        # 高影响力动作词（表示实际行动而非闲聊）
        action_words = [
            'announcing', 'signed', 'signing', 'effective immediately',
            'executive order', 'i am', 'we will', 'i will', 'just signed',
            'breaking', 'big news', 'historic', 'fired', 'appointed',
        ]

        detected_topic = 'unknown'
        max_matches = 0
        matched_keywords = []
        all_matched = []

        for topic, keywords in topic_keywords.items():
            matches = [kw for kw in keywords if kw in content]
            if len(matches) > max_matches:
                max_matches = len(matches)
                detected_topic = topic
                matched_keywords = matches
            all_matched.extend(matches)

        # 动作词加分（表示真正的政策行动）
        action_bonus = sum(1 for aw in action_words if aw in content)

        # 影响力评分
        impact = min(10, max_matches * 2 + action_bonus * 2) if max_matches > 0 else 2

        # 置信度：关键词数量 + 动作词加分
        confidence = min(75, max_matches * 20 + action_bonus * 15)

        # Polymarket搜索关键词优化：加上"trump"前缀
        search_keywords = ['trump'] + matched_keywords[:4]

        # 方向推断
        direction = 'YES'
        if any(w in content for w in ['ban', 'stop', 'end', 'cancel', 'terminate', 'withdraw']):
            direction = 'NO'  # 否定性行动

        return {
            'topic_category': detected_topic,
            'market_impact_score': impact,
            'impact_reasoning': f"关键词匹配: {', '.join(all_matched) or '无'}; 动作词: {action_bonus}个",
            'polymarket_keywords': search_keywords,
            'suggested_direction': direction,
            'direction_target': detected_topic,
            'confidence': confidence,
            'urgency': 'immediate' if impact >= 7 else ('watch' if impact >= 5 else 'low'),
            'is_actionable': impact >= 5,
            'post_id': post.get('id'),
            'post_source': post.get('source'),
            '_fallback': True,
        }

    @staticmethod
    def _default_value(field):
        """Return default value for missing analysis fields."""
        defaults = {
            'topic_category': 'unknown',
            'market_impact_score': 1,
            'polymarket_keywords': ['trump'],
            'suggested_direction': 'YES',
            'direction_target': 'unknown',
            'confidence': 0,
            'is_actionable': False,
            'urgency': 'low',
            'impact_reasoning': 'Analysis incomplete',
        }
        return defaults.get(field)
