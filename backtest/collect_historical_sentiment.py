#!/usr/bin/env python3
"""
Real Sentiment Backtest - Crawl historical Guba posts, analyze with SnowNLP,
correlate with price movements, and run a proper sentiment-based backtest.

Usage:
    python -m backtest.collect_historical_sentiment
"""

import csv
import json
import logging
import os
import random
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from snownlp import SnowNLP

# Ensure project root on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backtest.engine import BacktestEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ======================================================================
# Config
# ======================================================================

STOCKS = [
    {"code": "600519", "name": "贵州茅台"},
    {"code": "000001", "name": "平安银行"},
    {"code": "300750", "name": "宁德时代"},
    {"code": "601318", "name": "中国平安"},
    {"code": "000333", "name": "美的集团"},
    {"code": "600036", "name": "招商银行"},
    {"code": "002594", "name": "比亚迪"},
    {"code": "601899", "name": "紫金矿业"},
    {"code": "600900", "name": "长江电力"},
    {"code": "002714", "name": "牧原股份"},
    {"code": "601012", "name": "隆基绿能"},
    {"code": "300059", "name": "东方财富"},
    {"code": "002475", "name": "立讯精密"},
    {"code": "600276", "name": "恒瑞医药"},
    {"code": "000858", "name": "五粮液"},
]

PAGES_PER_STOCK = 10          # pages 1-10 per stock
REQUEST_INTERVAL = 2.5        # seconds between requests
REQUEST_TIMEOUT = 20          # seconds
SENTIMENT_CSV = os.path.join(_PROJECT_ROOT, "backtest", "historical_sentiment.csv")
PRICE_CSV = os.path.join(_PROJECT_ROOT, "backtest", "historical_data.csv")
POSTS_CACHE_CSV = os.path.join(_PROJECT_ROOT, "backtest", "crawled_posts.csv")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]

LIST_URL = "https://guba.eastmoney.com/list,{code}.html"
LIST_URL_PAGED = "https://guba.eastmoney.com/list,{code},f_{page}.html"

# East Money kline API for price data
KLINE_API = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


# ======================================================================
# Step 0: Fetch price data from East Money API
# ======================================================================

def get_secid(stock_code: str) -> str:
    """Generate East Money secid format."""
    if stock_code.startswith("6"):
        return f"1.{stock_code}"
    return f"0.{stock_code}"


def fetch_price_data_eastmoney(stock_code: str, start_date: str, end_date: str,
                                session: requests.Session) -> Optional[pd.DataFrame]:
    """Fetch daily kline data from East Money push API."""
    secid = get_secid(stock_code)
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",  # daily
        "fqt": "1",    # qfq (forward adjusted)
        "beg": start_date.replace("-", ""),
        "end": end_date.replace("-", ""),
        "lmt": "500",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }

    try:
        time.sleep(0.5)
        resp = session.get(KLINE_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch price for {stock_code}: {e}")
        return None

    klines = data.get("data", {}).get("klines", [])
    if not klines:
        logger.warning(f"No kline data for {stock_code}")
        return None

    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 7:
            rows.append({
                "date": parts[0],
                "stock_code": stock_code,
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
            })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_all_price_data(stock_codes: List[str], start_date: str,
                          end_date: str) -> pd.DataFrame:
    """Fetch price data for all stocks from East Money API."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://quote.eastmoney.com/",
    })

    frames = []
    for i, code in enumerate(stock_codes, 1):
        logger.info(f"  Fetching price data {code} ({i}/{len(stock_codes)})")
        df = fetch_price_data_eastmoney(code, start_date, end_date, session)
        if df is not None and not df.empty:
            frames.append(df)

    session.close()

    if not frames:
        return pd.DataFrame(columns=["date", "stock_code", "open", "high",
                                      "low", "close", "volume"])

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["stock_code", "date"]).reset_index(drop=True)
    return result


# ======================================================================
# Step 1: Crawl historical Guba posts
# ======================================================================

def parse_time(time_str: str) -> Optional[datetime]:
    """Parse Guba time formats into datetime, return None on failure."""
    if not time_str or not isinstance(time_str, str):
        return None
    time_str = time_str.strip()
    now = datetime.now()

    # Full datetime
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue

    # MM-DD HH:MM (no year)
    match = re.match(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", time_str)
    if match:
        month, day, hour, minute = (int(g) for g in match.groups())
        try:
            result = now.replace(month=month, day=day, hour=hour,
                                 minute=minute, second=0, microsecond=0)
            if result > now:
                result = result.replace(year=now.year - 1)
            return result
        except ValueError:
            pass

    # HH:MM only (today)
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if match:
        try:
            return now.replace(hour=int(match.group(1)),
                               minute=int(match.group(2)),
                               second=0, microsecond=0)
        except ValueError:
            pass

    # 今天/昨天
    if "今天" in time_str:
        t_match = re.search(r"(\d{1,2}):(\d{2})", time_str)
        if t_match:
            try:
                return now.replace(hour=int(t_match.group(1)),
                                   minute=int(t_match.group(2)),
                                   second=0, microsecond=0)
            except ValueError:
                pass

    if "昨天" in time_str:
        yesterday = now - timedelta(days=1)
        t_match = re.search(r"(\d{1,2}):(\d{2})", time_str)
        if t_match:
            try:
                return yesterday.replace(hour=int(t_match.group(1)),
                                         minute=int(t_match.group(2)),
                                         second=0, microsecond=0)
            except ValueError:
                pass

    return None


def crawl_stock_pages(stock_code: str, stock_name: str,
                      session: requests.Session) -> List[dict]:
    """Crawl pages 1-10 for a stock, return list of raw post dicts."""
    all_posts = []

    for page in range(1, PAGES_PER_STOCK + 1):
        # Rate limit
        time.sleep(REQUEST_INTERVAL + random.uniform(0, 1.0))
        session.headers["User-Agent"] = random.choice(USER_AGENTS)

        if page == 1:
            url = LIST_URL.format(code=stock_code)
        else:
            url = LIST_URL_PAGED.format(code=stock_code, page=page)

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
        except Exception as e:
            logger.warning(f"  [{stock_code}] Page {page} request failed: {e}")
            continue

        # Parse embedded JSON: var article_list={...};
        match = re.search(r'var\s+article_list\s*=\s*(\{.*?\})\s*;',
                          resp.text, re.DOTALL)
        if not match:
            logger.warning(f"  [{stock_code}] Page {page}: no article_list found")
            continue

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"  [{stock_code}] Page {page}: JSON parse error: {e}")
            continue

        post_list = data.get("re", [])
        if not post_list:
            logger.info(f"  [{stock_code}] Page {page}: empty post list, stopping")
            break

        page_count = 0
        for item in post_list:
            title = (item.get("post_title", "") or
                     item.get("title", "") or "").strip()
            if not title or len(title) < 3:
                continue

            time_str = (item.get("post_publish_time") or
                        item.get("publish_time") or
                        item.get("post_display_time") or "")
            pub_time = parse_time(time_str)
            if pub_time is None:
                continue

            all_posts.append({
                "stock_code": stock_code,
                "stock_name": stock_name,
                "title": title,
                "publish_time": pub_time,
                "date": pub_time.strftime("%Y-%m-%d"),
            })
            page_count += 1

        logger.info(f"  [{stock_code}] Page {page}: {page_count} posts "
                     f"(total: {len(all_posts)})")

    return all_posts


def crawl_all_stocks() -> List[dict]:
    """Crawl historical posts for all 15 stocks."""
    session = requests.Session()
    session.headers.update({
        "Referer": "https://guba.eastmoney.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    })

    all_posts = []
    total_stocks = len(STOCKS)

    for idx, stock in enumerate(STOCKS, 1):
        code = stock["code"]
        name = stock["name"]
        logger.info(f"[{idx}/{total_stocks}] Crawling {code} {name} ...")
        posts = crawl_stock_pages(code, name, session)
        all_posts.extend(posts)
        logger.info(f"[{idx}/{total_stocks}] {code} {name}: {len(posts)} posts collected")

    session.close()
    return all_posts


# ======================================================================
# Step 2: SnowNLP sentiment analysis
# ======================================================================

def analyze_sentiment(posts: List[dict]) -> List[dict]:
    """Run SnowNLP on each post title, add sentiment scores."""
    logger.info(f"Running SnowNLP sentiment analysis on {len(posts)} posts...")

    for post in posts:
        title = post["title"]
        try:
            raw_score = SnowNLP(title).sentiments  # [0, 1]
        except Exception:
            raw_score = 0.5

        post["raw_sentiment"] = round(raw_score, 4)
        post["normalized_sentiment"] = round(raw_score * 2 - 1, 4)  # [-1, 1]
        post["is_bullish"] = 1 if raw_score > 0.6 else 0
        post["is_bearish"] = 1 if raw_score < 0.4 else 0

    logger.info("Sentiment analysis complete.")
    return posts


# ======================================================================
# Step 3: Aggregate daily sentiment per stock
# ======================================================================

def aggregate_daily_sentiment(posts: List[dict]) -> pd.DataFrame:
    """Group posts by (date, stock_code) and compute daily sentiment metrics."""
    # Group posts
    groups = defaultdict(list)
    for post in posts:
        key = (post["date"], post["stock_code"])
        groups[key].append(post)

    rows = []
    for (date, stock_code), group_posts in sorted(groups.items()):
        sentiments = [p["normalized_sentiment"] for p in group_posts]
        bullish_count = sum(p["is_bullish"] for p in group_posts)
        volume = len(group_posts)

        avg_sentiment = statistics.mean(sentiments)
        bullish_ratio = bullish_count / volume
        disagreement = statistics.pstdev(sentiments) if volume > 1 else 0.0

        rows.append({
            "date": date,
            "stock_code": stock_code,
            "avg_sentiment": round(avg_sentiment, 4),
            "bullish_ratio": round(bullish_ratio, 4),
            "comment_volume": volume,
            "disagreement": round(disagreement, 4),
        })

    df = pd.DataFrame(rows)
    logger.info(f"Daily sentiment aggregated: {len(df)} date-stock records "
                f"across {df['date'].nunique()} dates, "
                f"{df['stock_code'].nunique()} stocks")
    return df


# ======================================================================
# Step 4: Save sentiment CSV
# ======================================================================

def save_sentiment_csv(df: pd.DataFrame, path: str):
    """Save sentiment dataframe to CSV."""
    df.to_csv(path, index=False)
    logger.info(f"Sentiment data saved to {path} ({len(df)} rows)")


# ======================================================================
# Step 5: Generate BUY signals from real sentiment
# ======================================================================

def generate_sentiment_signals(sentiment_df: pd.DataFrame) -> List[dict]:
    """
    Generate BUY signals based on real sentiment data.

    Buy when:
    - avg_sentiment > 0.1 (positive sentiment)
    - bullish_ratio > 0.5 (majority bullish)
    - comment_volume is above the stock's average volume

    Extra score for:
    - Sentiment improving vs yesterday
    - Volume surging vs average
    """
    stock_map = {s["code"]: s["name"] for s in STOCKS}
    signals = []

    sentiment_df = sentiment_df.sort_values(["stock_code", "date"]).copy()

    for stock_code, group in sentiment_df.groupby("stock_code"):
        group = group.sort_values("date").reset_index(drop=True)
        avg_volume = group["comment_volume"].mean()

        for i, row in group.iterrows():
            score = 10  # base score
            conditions_met = 0

            # Condition 1: Positive sentiment
            if row["avg_sentiment"] > 0.1:
                score += 25
                conditions_met += 1

            # Condition 2: Majority bullish
            if row["bullish_ratio"] > 0.5:
                score += 20
                conditions_met += 1

            # Condition 3: Above-average comment volume
            if avg_volume > 0 and row["comment_volume"] > avg_volume:
                score += 15
                conditions_met += 1

            # Bonus: sentiment improving vs yesterday
            idx_in_group = group.index.get_loc(i) if i in group.index else None
            if idx_in_group is not None and idx_in_group > 0:
                prev_sentiment = group.iloc[idx_in_group - 1]["avg_sentiment"]
                sentiment_delta = row["avg_sentiment"] - prev_sentiment
                if sentiment_delta > 0.05:
                    score += 15  # sentiment momentum
                    conditions_met += 1

            # Bonus: volume surge
            if avg_volume > 0 and row["comment_volume"] > avg_volume * 1.5:
                score += 10  # volume surge bonus

            # Bonus: low disagreement (consensus)
            if row["disagreement"] < 0.3:
                score += 5

            # Need at least 2 conditions met to generate signal
            if conditions_met >= 2:
                signals.append({
                    "date": row["date"],
                    "stock_code": stock_code,
                    "stock_name": stock_map.get(stock_code, ""),
                    "score": min(score, 100),
                    "signal": "BUY",
                    "avg_sentiment": row["avg_sentiment"],
                    "bullish_ratio": row["bullish_ratio"],
                    "comment_volume": row["comment_volume"],
                })

    signals.sort(key=lambda s: (s["date"], -s["score"]))
    logger.info(f"Sentiment signals generated: {len(signals)} BUY signals "
                f"across {len(set(s['stock_code'] for s in signals))} stocks")
    return signals


# ======================================================================
# Step 6: Generate random baseline signals
# ======================================================================

def generate_random_baseline(dates: List[str], stock_codes: List[str],
                             signal_prob: float = 0.03,
                             seed: int = 42) -> List[dict]:
    """Random baseline: each stock has signal_prob chance per day."""
    rng = np.random.RandomState(seed)
    stock_map = {s["code"]: s["name"] for s in STOCKS}
    signals = []

    for code in stock_codes:
        for d in dates:
            if rng.random() < signal_prob:
                signals.append({
                    "date": d,
                    "stock_code": code,
                    "stock_name": stock_map.get(code, ""),
                    "score": int(rng.uniform(40, 90)),
                    "signal": "BUY",
                })

    signals.sort(key=lambda s: (s["date"], -s["score"]))
    return signals


# ======================================================================
# Step 7: Generate heuristic (technical) signals for comparison
# ======================================================================

def generate_heuristic_signals(price_data: pd.DataFrame) -> List[dict]:
    """Technical indicator baseline (MA crossover + volume surge)."""
    stock_map = {s["code"]: s["name"] for s in STOCKS}
    signals = []

    for code, group in price_data.groupby("stock_code"):
        df = group.sort_values("date").copy()
        if len(df) < 21:
            continue

        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["vol_ma5"] = df["volume"].rolling(5).mean()
        df["prev_ma5"] = df["ma5"].shift(1)
        df["prev_ma20"] = df["ma20"].shift(1)

        for _, row in df.iterrows():
            if pd.isna(row["ma20"]) or pd.isna(row["vol_ma5"]):
                continue

            score = 10
            conds = 0

            # Golden cross
            if (not pd.isna(row["prev_ma5"]) and not pd.isna(row["prev_ma20"])
                    and row["prev_ma5"] <= row["prev_ma20"]
                    and row["ma5"] > row["ma20"]):
                score += 35
                conds += 1

            # Volume surge
            if row["vol_ma5"] > 0 and row["volume"] > row["vol_ma5"] * 1.5:
                score += 30
                conds += 1

            # Close above MA20
            if row["close"] > row["ma20"]:
                score += 25
                conds += 1

            if conds >= 2:
                sig_date = row["date"]
                if hasattr(sig_date, "strftime"):
                    sig_date = sig_date.strftime("%Y-%m-%d")
                signals.append({
                    "date": sig_date,
                    "stock_code": code,
                    "stock_name": stock_map.get(code, ""),
                    "score": score,
                    "signal": "BUY",
                })

    signals.sort(key=lambda s: (s["date"], -s["score"]))
    return signals


# ======================================================================
# Step 8: Run backtest and compare
# ======================================================================

def run_backtest_with_signals(signals: List[dict], price_data: pd.DataFrame,
                              start_date: str, end_date: str,
                              label: str) -> dict:
    """Run backtest engine and print results."""
    engine = BacktestEngine()

    # Filter signals to backtest range
    in_range = [s for s in signals if start_date <= s["date"] <= end_date]
    if not in_range:
        print(f"\n  [{label}] No signals in range {start_date} ~ {end_date}")
        return {"trades": [], "metrics": {}}

    print(f"\n  [{label}] Signals: {len(in_range)}, "
          f"Stocks: {len(set(s['stock_code'] for s in in_range))}")

    result = engine.run(
        signals=signals,
        price_data=price_data,
        start_date=start_date,
        end_date=end_date,
    )

    metrics = result.get("metrics", {})
    trades = result.get("trades", [])

    print(f"  [{label}] Trades: {metrics.get('total_trades', 0)}")
    print(f"  [{label}] Total Return: {metrics.get('total_return', 0):+.2f}%")
    print(f"  [{label}] Win Rate: {metrics.get('win_rate', 0):.1f}%")
    print(f"  [{label}] Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.4f}")
    print(f"  [{label}] Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
    print(f"  [{label}] Avg Return/Trade: {metrics.get('avg_return', 0):+.4f}%")
    print(f"  [{label}] Best Trade: {metrics.get('best_trade', 0):+.4f}%")
    print(f"  [{label}] Worst Trade: {metrics.get('worst_trade', 0):+.4f}%")
    pf = metrics.get('profit_factor', 0)
    pf_str = f"{pf:.4f}" if np.isfinite(pf) else "inf"
    print(f"  [{label}] Profit Factor: {pf_str}")
    print(f"  [{label}] Avg Hold Days: {metrics.get('avg_hold_days', 0):.1f}")

    if trades:
        print(f"\n  [{label}] Sample trades (last 5):")
        print(f"    {'Stock':>10s}  {'Entry':>12s}  {'Exit':>12s}  {'Return%':>8s}  {'Reason':>12s}")
        print(f"    {'-'*54}")
        for t in trades[-5:]:
            sc = str(t.get('stock_code', '')).zfill(6)
            print(f"    {sc:>10s}  "
                  f"{str(t.get('entry_date',''))[:10]:>12s}  "
                  f"{str(t.get('exit_date',''))[:10]:>12s}  "
                  f"{t.get('return_pct',0):>+8.2f}  "
                  f"{str(t.get('exit_reason','')):>12s}")

    return result


# ======================================================================
# Main
# ======================================================================

def main():
    print("=" * 70)
    print("  REAL SENTIMENT BACKTEST")
    print("  Crawl Guba -> SnowNLP Analysis -> Sentiment Signals -> Backtest")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Phase 1: Crawl historical posts
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PHASE 1: Crawling historical posts from East Money Guba")
    print("=" * 70)

    # Check for cached posts first
    if os.path.exists(POSTS_CACHE_CSV):
        logger.info(f"Loading cached posts from {POSTS_CACHE_CSV}")
        cached_df = pd.read_csv(POSTS_CACHE_CSV)
        all_posts = []
        for _, row in cached_df.iterrows():
            all_posts.append({
                "stock_code": str(row["stock_code"]).zfill(6),
                "stock_name": row["stock_name"],
                "title": row["title"],
                "publish_time": datetime.strptime(str(row["publish_time"])[:19], "%Y-%m-%d %H:%M:%S"),
                "date": row["date"],
            })
        logger.info(f"Loaded {len(all_posts)} cached posts")
    else:
        all_posts = crawl_all_stocks()
        # Save cache
        if all_posts:
            cache_rows = []
            for p in all_posts:
                cache_rows.append({
                    "stock_code": p["stock_code"],
                    "stock_name": p["stock_name"],
                    "title": p["title"],
                    "publish_time": p["publish_time"].strftime("%Y-%m-%d %H:%M:%S"),
                    "date": p["date"],
                })
            pd.DataFrame(cache_rows).to_csv(POSTS_CACHE_CSV, index=False)
            logger.info(f"Posts cached to {POSTS_CACHE_CSV}")

    if not all_posts:
        print("[ERROR] No posts crawled. Cannot proceed.")
        sys.exit(1)

    # Stats
    dates = sorted(set(p["date"] for p in all_posts))
    print(f"\n  Total posts crawled: {len(all_posts)}")
    print(f"  Date range: {dates[0]} ~ {dates[-1]}")
    print(f"  Unique dates: {len(dates)}")
    print(f"  Stocks with posts: {len(set(p['stock_code'] for p in all_posts))}")

    # Posts per stock
    stock_counts = defaultdict(int)
    for p in all_posts:
        stock_counts[p["stock_code"]] += 1
    print(f"\n  Posts per stock:")
    for code in sorted(stock_counts.keys()):
        name = next((s["name"] for s in STOCKS if s["code"] == code), "")
        print(f"    {code} {name}: {stock_counts[code]}")

    # ------------------------------------------------------------------
    # Phase 2: Sentiment analysis
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PHASE 2: SnowNLP Sentiment Analysis")
    print("=" * 70)

    all_posts = analyze_sentiment(all_posts)

    # Sentiment distribution
    sentiments = [p["normalized_sentiment"] for p in all_posts]
    bullish_pct = sum(1 for p in all_posts if p["is_bullish"]) / len(all_posts) * 100
    bearish_pct = sum(1 for p in all_posts if p["is_bearish"]) / len(all_posts) * 100
    neutral_pct = 100 - bullish_pct - bearish_pct
    print(f"\n  Sentiment Distribution:")
    print(f"    Bullish (>0.6): {bullish_pct:.1f}%")
    print(f"    Neutral:        {neutral_pct:.1f}%")
    print(f"    Bearish (<0.4): {bearish_pct:.1f}%")
    print(f"    Avg sentiment:  {statistics.mean(sentiments):.4f}")
    print(f"    Std deviation:  {statistics.stdev(sentiments):.4f}")

    # ------------------------------------------------------------------
    # Phase 3: Aggregate daily sentiment
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PHASE 3: Daily Sentiment Aggregation")
    print("=" * 70)

    sentiment_df = aggregate_daily_sentiment(all_posts)

    # Save to CSV
    save_sentiment_csv(sentiment_df, SENTIMENT_CSV)

    print(f"\n  Sample daily sentiment (first 10 rows):")
    print(sentiment_df.head(10).to_string(index=False))

    # ------------------------------------------------------------------
    # Phase 4: Fetch price data covering sentiment period
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PHASE 4: Fetching Price Data (East Money API)")
    print("=" * 70)

    # Determine what date range we need: sentiment dates + buffer
    sentiment_dates_sorted = sorted(sentiment_df["date"].unique())
    # Start 30 days before earliest sentiment date (for MA warmup)
    from datetime import datetime as dt_cls
    earliest_sentiment = dt_cls.strptime(sentiment_dates_sorted[0], "%Y-%m-%d")
    latest_sentiment = dt_cls.strptime(sentiment_dates_sorted[-1], "%Y-%m-%d")
    price_start = (earliest_sentiment - timedelta(days=45)).strftime("%Y-%m-%d")
    price_end = (latest_sentiment + timedelta(days=10)).strftime("%Y-%m-%d")

    PRICE_CACHE = os.path.join(_PROJECT_ROOT, "backtest", "eastmoney_price_cache.csv")

    if os.path.exists(PRICE_CACHE):
        logger.info(f"Loading cached price data from {PRICE_CACHE}")
        price_data = pd.read_csv(PRICE_CACHE)
        price_data["date"] = pd.to_datetime(price_data["date"])
    else:
        stock_codes = [s["code"] for s in STOCKS]
        print(f"  Fetching price data for {len(stock_codes)} stocks: {price_start} ~ {price_end}")
        price_data = fetch_all_price_data(stock_codes, price_start, price_end)
        if not price_data.empty:
            price_data.to_csv(PRICE_CACHE, index=False)
            logger.info(f"Price data cached to {PRICE_CACHE}")

    # Also load the existing historical_data.csv and merge if available
    if os.path.exists(PRICE_CSV):
        old_price = pd.read_csv(PRICE_CSV)
        old_price["date"] = pd.to_datetime(old_price["date"])
        old_price["stock_code"] = old_price["stock_code"].astype(str).str.zfill(6)
        if not price_data.empty:
            price_data["stock_code"] = price_data["stock_code"].astype(str).str.zfill(6)
            price_data = pd.concat([old_price, price_data], ignore_index=True)
            price_data = price_data.drop_duplicates(subset=["date", "stock_code"],
                                                     keep="last")
        else:
            price_data = old_price

    price_data = price_data.sort_values(["stock_code", "date"]).reset_index(drop=True)

    print(f"  Price records: {len(price_data)}")
    print(f"  Stocks: {price_data['stock_code'].nunique()}")
    price_dates = price_data["date"].dt.strftime("%Y-%m-%d")
    print(f"  Date range: {price_dates.min()} ~ {price_dates.max()}")

    # Determine backtest range from overlap
    sentiment_dates = set(sentiment_df["date"].unique())
    price_date_set = set(price_dates.unique())
    overlap_dates = sorted(sentiment_dates & price_date_set)

    if not overlap_dates:
        print("\n[WARN] No exact date overlap between sentiment and price data.")
        print(f"  Sentiment dates: {sentiment_dates_sorted[:5]} ... {sentiment_dates_sorted[-5:]}")
        print(f"  Price dates: {sorted(price_date_set)[:5]} ... {sorted(price_date_set)[-5:]}")
        # Use the full price range that covers the sentiment period
        start_date = sentiment_dates_sorted[0]
        end_date = sentiment_dates_sorted[-1]
        print(f"\n  Using sentiment date range for backtest: {start_date} ~ {end_date}")
    else:
        start_date = overlap_dates[0]
        end_date = overlap_dates[-1]
        print(f"\n  Overlapping dates: {len(overlap_dates)}")
        print(f"  Backtest range: {start_date} ~ {end_date}")

    # ------------------------------------------------------------------
    # Phase 5: Generate signals and run backtests
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PHASE 5: Signal Generation & Backtest Comparison")
    print("=" * 70)

    # 5a: Real sentiment signals
    print("\n" + "-" * 70)
    print("  Strategy A: REAL SENTIMENT SIGNALS")
    print("-" * 70)
    sentiment_signals = generate_sentiment_signals(sentiment_df)

    if sentiment_signals:
        sig_dates = [s["date"] for s in sentiment_signals]
        print(f"  Signal date range: {min(sig_dates)} ~ {max(sig_dates)}")
        print(f"  Avg score: {np.mean([s['score'] for s in sentiment_signals]):.1f}")

    result_sentiment = run_backtest_with_signals(
        sentiment_signals, price_data, start_date, end_date,
        "SENTIMENT"
    )

    # 5b: Random baseline
    print("\n" + "-" * 70)
    print("  Strategy B: RANDOM BASELINE")
    print("-" * 70)
    all_price_dates = sorted(price_dates.unique())
    stock_codes = [s["code"] for s in STOCKS]
    random_signals = generate_random_baseline(all_price_dates, stock_codes)
    print(f"  Random signals: {len(random_signals)}")

    result_random = run_backtest_with_signals(
        random_signals, price_data, start_date, end_date,
        "RANDOM"
    )

    # 5c: Technical heuristic baseline
    print("\n" + "-" * 70)
    print("  Strategy C: TECHNICAL HEURISTIC (MA Crossover + Volume)")
    print("-" * 70)
    heuristic_signals = generate_heuristic_signals(price_data)
    print(f"  Heuristic signals: {len(heuristic_signals)}")

    result_heuristic = run_backtest_with_signals(
        heuristic_signals, price_data, start_date, end_date,
        "HEURISTIC"
    )

    # ------------------------------------------------------------------
    # Phase 6: Comparison Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  FINAL COMPARISON")
    print("=" * 70)

    strategies = [
        ("REAL SENTIMENT", result_sentiment),
        ("RANDOM BASELINE", result_random),
        ("TECHNICAL HEURISTIC", result_heuristic),
    ]

    print(f"\n  {'Strategy':<25s} {'Trades':>7s} {'Return%':>9s} {'WinRate%':>9s} "
          f"{'Sharpe':>8s} {'MaxDD%':>8s} {'AvgRet%':>9s} {'PF':>8s}")
    print(f"  {'-'*85}")

    for name, result in strategies:
        m = result.get("metrics", {})
        trades_n = m.get("total_trades", 0)
        total_ret = m.get("total_return", 0)
        win_rate = m.get("win_rate", 0)
        sharpe = m.get("sharpe_ratio", 0)
        max_dd = m.get("max_drawdown", 0)
        avg_ret = m.get("avg_return", 0)
        pf = m.get("profit_factor", 0)
        pf_str = f"{pf:.4f}" if np.isfinite(pf) else "inf"

        print(f"  {name:<25s} {trades_n:>7d} {total_ret:>+9.2f} {win_rate:>9.1f} "
              f"{sharpe:>8.4f} {max_dd:>8.2f} {avg_ret:>+9.4f} {pf_str:>8s}")

    # ------------------------------------------------------------------
    # Phase 7: Sentiment-Price Correlation Analysis
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  SENTIMENT-PRICE CORRELATION ANALYSIS")
    print("=" * 70)

    # Merge sentiment with next-day price returns
    price_data_str = price_data.copy()
    price_data_str["date_str"] = price_data_str["date"].dt.strftime("%Y-%m-%d")
    price_data_str["stock_code"] = price_data_str["stock_code"].astype(str)

    # Compute daily returns
    price_data_str = price_data_str.sort_values(["stock_code", "date"])
    price_data_str["next_day_return"] = (
        price_data_str.groupby("stock_code")["close"].pct_change().shift(-1) * 100
    )

    # Ensure stock_code types match
    sentiment_df["stock_code"] = sentiment_df["stock_code"].astype(str)
    # Pad stock codes to 6 digits
    sentiment_df["stock_code"] = sentiment_df["stock_code"].str.zfill(6)
    price_data_str["stock_code"] = price_data_str["stock_code"].str.zfill(6)

    merged = sentiment_df.merge(
        price_data_str[["date_str", "stock_code", "next_day_return", "close"]],
        left_on=["date", "stock_code"],
        right_on=["date_str", "stock_code"],
        how="inner",
    )

    if len(merged) > 5:
        # Overall correlation
        valid = merged.dropna(subset=["next_day_return", "avg_sentiment"])
        if len(valid) > 5:
            corr_sentiment = valid["avg_sentiment"].corr(valid["next_day_return"])
            corr_bullish = valid["bullish_ratio"].corr(valid["next_day_return"])
            corr_volume = valid["comment_volume"].corr(valid["next_day_return"])

            print(f"\n  Correlations with next-day return (n={len(valid)}):")
            print(f"    avg_sentiment  vs return: {corr_sentiment:+.4f}")
            print(f"    bullish_ratio  vs return: {corr_bullish:+.4f}")
            print(f"    comment_volume vs return: {corr_volume:+.4f}")

            # Quintile analysis
            if len(valid) >= 10:
                valid = valid.sort_values("avg_sentiment")
                n = len(valid)
                q_size = n // 3
                if q_size > 0:
                    bottom_tercile = valid.iloc[:q_size]["next_day_return"].mean()
                    mid_tercile = valid.iloc[q_size:2*q_size]["next_day_return"].mean()
                    top_tercile = valid.iloc[2*q_size:]["next_day_return"].mean()

                    print(f"\n  Sentiment Tercile Analysis:")
                    print(f"    Bottom tercile (bearish) avg return: {bottom_tercile:+.4f}%")
                    print(f"    Middle tercile (neutral) avg return: {mid_tercile:+.4f}%")
                    print(f"    Top tercile (bullish) avg return:    {top_tercile:+.4f}%")
                    print(f"    Spread (top - bottom):               {top_tercile - bottom_tercile:+.4f}%")
    else:
        print(f"\n  [WARN] Only {len(merged)} merged records, insufficient for correlation")
        print(f"  Sentiment dates: {sorted(sentiment_df['date'].unique())[:5]}")
        print(f"  Price dates: {sorted(price_data_str['date_str'].unique())[:5]}")

    print("\n" + "=" * 70)
    print("  BACKTEST COMPLETE")
    print("=" * 70)
    print(f"\n  Sentiment CSV: {SENTIMENT_CSV}")
    print(f"  Price CSV:     {PRICE_CSV}")


if __name__ == "__main__":
    main()
