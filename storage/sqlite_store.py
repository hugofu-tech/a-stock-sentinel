"""SQLite存储层 — 情绪数据持久化"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from contextlib import contextmanager

from storage.models import (
    SocialPost, SentimentResult, StockSentimentAggregate, DailyRecommendation
)

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sentiment.db")


class SentimentStore:
    """SQLite存储管理器"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # 写前日志，提高并发性能
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS social_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT DEFAULT '',
                    title TEXT NOT NULL,
                    content TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    publish_time TEXT NOT NULL,
                    url TEXT DEFAULT '',
                    read_count INTEGER DEFAULT 0,
                    comment_count INTEGER DEFAULT 0,
                    like_count INTEGER DEFAULT 0,
                    author_followers INTEGER DEFAULT 0,
                    crawl_time TEXT NOT NULL,
                    UNIQUE(source, url)
                );

                CREATE INDEX IF NOT EXISTS idx_posts_stock_date
                    ON social_posts(stock_code, publish_time);
                CREATE INDEX IF NOT EXISTS idx_posts_source_date
                    ON social_posts(source, publish_time);

                CREATE TABLE IF NOT EXISTS sentiment_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT DEFAULT '',
                    date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    comment_volume INTEGER DEFAULT 0,
                    avg_sentiment REAL DEFAULT 0,
                    bullish_ratio REAL DEFAULT 0,
                    disagreement_index REAL DEFAULT 0,
                    sentiment_change REAL DEFAULT 0,
                    volume_change REAL DEFAULT 0,
                    weighted_sentiment REAL DEFAULT 0,
                    score REAL DEFAULT 0,
                    UNIQUE(stock_code, date, source)
                );

                CREATE INDEX IF NOT EXISTS idx_scores_date
                    ON sentiment_scores(date);

                CREATE TABLE IF NOT EXISTS daily_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT DEFAULT '',
                    signal TEXT NOT NULL,
                    entry_price REAL DEFAULT 0,
                    total_score REAL DEFAULT 0,
                    sentiment_score REAL DEFAULT 0,
                    exit_date TEXT DEFAULT '',
                    exit_price REAL DEFAULT 0,
                    return_pct REAL DEFAULT 0,
                    exit_reason TEXT DEFAULT '',
                    UNIQUE(date, stock_code, signal)
                );

                CREATE TABLE IF NOT EXISTS backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    params TEXT DEFAULT '{}',
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    total_return REAL DEFAULT 0,
                    annualized_return REAL DEFAULT 0,
                    sharpe_ratio REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    details TEXT DEFAULT '{}'
                );
            """)

    # ========== 帖子操作 ==========

    def save_posts(self, posts: List[SocialPost]) -> int:
        """批量保存帖子，返回新增数量（自动去重）"""
        saved = 0
        with self._get_conn() as conn:
            for post in posts:
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO social_posts
                        (source, stock_code, stock_name, title, content, author,
                         publish_time, url, read_count, comment_count, like_count,
                         author_followers, crawl_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        post.source, post.stock_code, post.stock_name,
                        post.title, post.content, post.author,
                        post.publish_time.isoformat(), post.url,
                        post.read_count, post.comment_count, post.like_count,
                        post.author_followers,
                        post.crawl_time.isoformat() if post.crawl_time else datetime.now().isoformat()
                    ))
                    if conn.total_changes:
                        saved += 1
                except sqlite3.IntegrityError:
                    pass
        return saved

    def get_posts(self, stock_code: str, source: str = None,
                  hours: int = 24) -> List[SocialPost]:
        """获取指定股票最近N小时的帖子"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._get_conn() as conn:
            if source:
                rows = conn.execute("""
                    SELECT * FROM social_posts
                    WHERE stock_code = ? AND source = ? AND publish_time >= ?
                    ORDER BY publish_time DESC
                """, (stock_code, source, since)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM social_posts
                    WHERE stock_code = ? AND publish_time >= ?
                    ORDER BY publish_time DESC
                """, (stock_code, since)).fetchall()
        return [self._row_to_post(r) for r in rows]

    def get_post_count(self, stock_code: str, source: str = None,
                       hours: int = 24) -> int:
        """获取指定股票最近N小时的帖子数量"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._get_conn() as conn:
            if source:
                row = conn.execute("""
                    SELECT COUNT(*) as cnt FROM social_posts
                    WHERE stock_code = ? AND source = ? AND publish_time >= ?
                """, (stock_code, source, since)).fetchone()
            else:
                row = conn.execute("""
                    SELECT COUNT(*) as cnt FROM social_posts
                    WHERE stock_code = ? AND publish_time >= ?
                """, (stock_code, since)).fetchone()
        return row['cnt'] if row else 0

    # ========== 情绪分数操作 ==========

    def save_sentiment_aggregate(self, agg: StockSentimentAggregate):
        """保存/更新聚合情绪分数"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sentiment_scores
                (stock_code, stock_name, date, source, comment_volume,
                 avg_sentiment, bullish_ratio, disagreement_index,
                 sentiment_change, volume_change, weighted_sentiment, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                agg.stock_code, agg.stock_name, agg.date, agg.source,
                agg.comment_volume, agg.avg_sentiment, agg.bullish_ratio,
                agg.disagreement_index, agg.sentiment_change, agg.volume_change,
                agg.weighted_sentiment, agg.score
            ))

    def get_sentiment(self, stock_code: str, date: str,
                      source: str = "combined") -> Optional[StockSentimentAggregate]:
        """获取指定日期的情绪分数"""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT * FROM sentiment_scores
                WHERE stock_code = ? AND date = ? AND source = ?
            """, (stock_code, date, source)).fetchone()
        return self._row_to_aggregate(row) if row else None

    def get_sentiment_history(self, stock_code: str, days: int = 30,
                              source: str = "combined") -> List[StockSentimentAggregate]:
        """获取情绪历史"""
        since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM sentiment_scores
                WHERE stock_code = ? AND source = ? AND date >= ?
                ORDER BY date ASC
            """, (stock_code, source, since)).fetchall()
        return [self._row_to_aggregate(r) for r in rows]

    def get_all_sentiments_for_date(self, date: str,
                                    source: str = "combined") -> List[StockSentimentAggregate]:
        """获取某日所有股票的情绪分数"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM sentiment_scores
                WHERE date = ? AND source = ?
                ORDER BY score DESC
            """, (date, source)).fetchall()
        return [self._row_to_aggregate(r) for r in rows]

    # ========== 推荐记录操作 ==========

    def save_recommendation(self, rec: DailyRecommendation):
        """保存推荐记录"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO daily_recommendations
                (date, stock_code, stock_name, signal, entry_price,
                 total_score, sentiment_score, exit_date, exit_price,
                 return_pct, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec.date, rec.stock_code, rec.stock_name, rec.signal,
                rec.entry_price, rec.total_score, rec.sentiment_score,
                rec.exit_date, rec.exit_price, rec.return_pct, rec.exit_reason
            ))

    def get_open_positions(self) -> List[DailyRecommendation]:
        """获取未平仓的推荐（signal=BUY且exit_date为空）"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM daily_recommendations
                WHERE signal = 'BUY' AND (exit_date = '' OR exit_date IS NULL)
                ORDER BY date DESC
            """).fetchall()
        return [self._row_to_recommendation(r) for r in rows]

    def update_exit(self, date: str, stock_code: str,
                    exit_date: str, exit_price: float,
                    return_pct: float, exit_reason: str):
        """更新平仓信息"""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE daily_recommendations
                SET exit_date = ?, exit_price = ?, return_pct = ?, exit_reason = ?
                WHERE date = ? AND stock_code = ? AND signal = 'BUY'
                AND (exit_date = '' OR exit_date IS NULL)
            """, (exit_date, exit_price, return_pct, exit_reason,
                  date, stock_code))

    # ========== 回测结果 ==========

    def save_backtest_result(self, strategy_name: str, params: dict,
                             start_date: str, end_date: str,
                             metrics: dict):
        """保存回测结果"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO backtest_results
                (run_date, strategy_name, params, start_date, end_date,
                 total_return, annualized_return, sharpe_ratio, max_drawdown,
                 win_rate, total_trades, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                strategy_name, json.dumps(params),
                start_date, end_date,
                metrics.get('total_return', 0),
                metrics.get('annualized_return', 0),
                metrics.get('sharpe_ratio', 0),
                metrics.get('max_drawdown', 0),
                metrics.get('win_rate', 0),
                metrics.get('total_trades', 0),
                json.dumps(metrics)
            ))

    # ========== 辅助方法 ==========

    @staticmethod
    def _row_to_post(row) -> SocialPost:
        return SocialPost(
            source=row['source'],
            stock_code=row['stock_code'],
            stock_name=row['stock_name'],
            title=row['title'],
            content=row['content'],
            author=row['author'],
            publish_time=datetime.fromisoformat(row['publish_time']),
            url=row['url'],
            read_count=row['read_count'],
            comment_count=row['comment_count'],
            like_count=row['like_count'],
            author_followers=row['author_followers'],
            crawl_time=datetime.fromisoformat(row['crawl_time'])
        )

    @staticmethod
    def _row_to_aggregate(row) -> StockSentimentAggregate:
        return StockSentimentAggregate(
            stock_code=row['stock_code'],
            stock_name=row['stock_name'],
            date=row['date'],
            source=row['source'],
            comment_volume=row['comment_volume'],
            avg_sentiment=row['avg_sentiment'],
            bullish_ratio=row['bullish_ratio'],
            disagreement_index=row['disagreement_index'],
            sentiment_change=row['sentiment_change'],
            volume_change=row['volume_change'],
            weighted_sentiment=row['weighted_sentiment'],
            score=row['score']
        )

    @staticmethod
    def _row_to_recommendation(row) -> DailyRecommendation:
        return DailyRecommendation(
            date=row['date'],
            stock_code=row['stock_code'],
            stock_name=row['stock_name'],
            signal=row['signal'],
            entry_price=row['entry_price'],
            total_score=row['total_score'],
            sentiment_score=row['sentiment_score'],
            exit_date=row['exit_date'],
            exit_price=row['exit_price'],
            return_pct=row['return_pct'],
            exit_reason=row['exit_reason']
        )

    def cleanup_old_posts(self, days: int = 90):
        """清理N天前的帖子数据"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute("DELETE FROM social_posts WHERE publish_time < ?", (cutoff,))

    def get_stats(self) -> Dict:
        """获取数据库统计信息"""
        with self._get_conn() as conn:
            posts = conn.execute("SELECT COUNT(*) as cnt FROM social_posts").fetchone()['cnt']
            scores = conn.execute("SELECT COUNT(*) as cnt FROM sentiment_scores").fetchone()['cnt']
            recs = conn.execute("SELECT COUNT(*) as cnt FROM daily_recommendations").fetchone()['cnt']
        return {'posts': posts, 'sentiment_scores': scores, 'recommendations': recs}
