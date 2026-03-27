#!/usr/bin/env python3
"""
Trump Social Media -> Polymarket Trading Signal System
Main Orchestrator

Pipeline:
1. Monitor Trump's Truth Social & X accounts for new posts
2. Deduplicate against previously seen posts
3. Analyze each new post via Claude API (LLM)
4. Search Polymarket for matching prediction markets
5. Generate trading signals (direction, size, confidence)
6. Send signals via email (and console output)

Usage:
    # Single run (for GitHub Actions / cron):
    python trump_sentinel.py

    # Continuous polling mode:
    python trump_sentinel.py --loop

    # Dry run (skip email, print only):
    python trump_sentinel.py --dry-run
"""

import argparse
import logging
import sys
import time
import json
import os
from datetime import datetime, timezone

from trump_config import POLL_INTERVAL, LOG_LEVEL
from post_store import PostStore
from trump_monitor import TrumpSocialMonitor
from llm_analyzer import LLMAnalyzer
from polymarket_client import PolymarketClient
from signal_generator import SignalGenerator
from email_notifier import EmailNotifier

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('trump_sentinel')


class TrumpSentinel:
    """Main orchestrator for the Trump -> Polymarket signal pipeline."""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.store = PostStore()
        self.monitor = TrumpSocialMonitor()
        self.analyzer = LLMAnalyzer()
        self.polymarket = PolymarketClient()
        self.signal_gen = SignalGenerator(self.polymarket)
        self.email = EmailNotifier()

        # Stats tracking
        self.stats = {
            'runs': 0,
            'posts_fetched': 0,
            'new_posts': 0,
            'signals_generated': 0,
            'emails_sent': 0,
        }

    def run_once(self):
        """Execute one full pipeline cycle.

        Returns:
            List of generated trading signals (may be empty).
        """
        self.stats['runs'] += 1
        run_start = time.time()
        logger.info(f"=== Pipeline run #{self.stats['runs']} ===")

        # Step 1: Fetch posts from all sources
        logger.info("Step 1: Fetching social media posts...")
        all_posts = self.monitor.fetch_all_posts(limit=20)
        self.stats['posts_fetched'] += len(all_posts)

        if not all_posts:
            logger.info("No posts fetched from any source")
            return []

        # Step 2: Filter new posts (deduplication)
        logger.info("Step 2: Deduplicating posts...")
        new_posts = self.store.get_new_posts(all_posts)
        self.stats['new_posts'] += len(new_posts)

        if not new_posts:
            logger.info("No new posts since last check")
            return []

        logger.info(f"Found {len(new_posts)} new posts to analyze")

        # Step 3: Analyze via LLM
        logger.info("Step 3: Analyzing posts with LLM...")
        analyzed = self.analyzer.analyze_batch(new_posts)

        # Mark posts as seen AFTER analysis (so failed analysis can be retried)
        self.store.mark_batch_seen(new_posts)

        # Filter to actionable analyses
        actionable = [a for a in analyzed if a['analysis'].get('is_actionable', False)]
        logger.info(f"Analyzed {len(analyzed)} posts, {len(actionable)} actionable")

        if not actionable:
            logger.info("No actionable posts in this batch")
            self._log_non_actionable(analyzed)
            return []

        # Step 4: Generate trading signals
        logger.info("Step 4: Generating trading signals...")
        signals = self.signal_gen.generate_signals_batch(actionable)
        self.stats['signals_generated'] += len(signals)

        if not signals:
            logger.info("No trading signals generated (no matching markets)")
            return []

        logger.info(f"Generated {len(signals)} trading signals")

        # Step 5: Send notifications
        logger.info("Step 5: Sending notifications...")
        if self.dry_run:
            logger.info("[DRY RUN] Printing signals to console only")
            for signal in signals:
                EmailNotifier._print_signal(signal)
        else:
            if self.email.is_configured():
                success = self.email.send_batch(signals)
                if success:
                    self.stats['emails_sent'] += 1
                    logger.info("Email sent successfully")
                else:
                    logger.error("Failed to send email")
            else:
                logger.warning("Email not configured, printing to console")
                for signal in signals:
                    EmailNotifier._print_signal(signal)

        # Save signals to file for record
        self._save_signals(signals)

        elapsed = time.time() - run_start
        logger.info(f"Pipeline run completed in {elapsed:.1f}s")

        return signals

    def run_loop(self, interval=None):
        """Run the pipeline continuously with polling interval.

        Args:
            interval: Polling interval in seconds (default from config).
        """
        interval = interval or POLL_INTERVAL
        logger.info(f"Starting continuous monitoring (interval: {interval}s)")
        logger.info(f"LLM configured: {self.analyzer.is_configured()}")
        logger.info(f"Twitter configured: {self.monitor.twitter.is_configured()}")
        logger.info(f"Email configured: {self.email.is_configured()}")

        try:
            while True:
                try:
                    self.run_once()
                except Exception as e:
                    logger.error(f"Pipeline error: {e}", exc_info=True)

                logger.debug(f"Sleeping {interval}s until next poll...")
                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Shutting down (Ctrl+C)")
            self._print_stats()

    def _log_non_actionable(self, analyzed):
        """Log summary of non-actionable posts for debugging."""
        for item in analyzed:
            post = item['post']
            analysis = item['analysis']
            logger.debug(
                f"Non-actionable: [{analysis.get('topic_category')}] "
                f"impact={analysis.get('market_impact_score')}/10, "
                f"conf={analysis.get('confidence')}% - "
                f"{post.get('content', '')[:80]}..."
            )

    def _save_signals(self, signals):
        """Save generated signals to a JSON file for records."""
        os.makedirs('data', exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filepath = f"data/signals_{timestamp}.json"

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(signals, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"Signals saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save signals: {e}")

    def _print_stats(self):
        """Print session statistics."""
        print("\n" + "="*50)
        print("  Trump Sentinel - Session Stats")
        print("="*50)
        for key, value in self.stats.items():
            print(f"  {key}: {value}")
        print(f"  store: {self.store.stats()}")
        print("="*50)


def main():
    parser = argparse.ArgumentParser(
        description='Trump Social Media -> Polymarket Trading Signal System'
    )
    parser.add_argument(
        '--loop', action='store_true',
        help='Run continuously with polling'
    )
    parser.add_argument(
        '--interval', type=int, default=None,
        help=f'Polling interval in seconds (default: {POLL_INTERVAL})'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Skip email sending, print signals to console'
    )

    args = parser.parse_args()

    print("="*60)
    print("  Trump Social Media -> Polymarket Trading Signals")
    print("  Phase 1: Monitor + Analyze + Signal + Notify")
    print("="*60)
    print(f"  Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Mode: {'continuous' if args.loop else 'single run'}")
    print(f"  Dry run: {args.dry_run}")
    print("="*60 + "\n")

    sentinel = TrumpSentinel(dry_run=args.dry_run)

    if args.loop:
        sentinel.run_loop(interval=args.interval)
    else:
        signals = sentinel.run_once()
        sentinel._print_stats()

        if not signals:
            print("\nNo trading signals generated in this run.")
            sys.exit(0)
        else:
            print(f"\nGenerated {len(signals)} trading signal(s).")
            sys.exit(0)


if __name__ == '__main__':
    main()
