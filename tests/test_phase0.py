"""Phase 0 基础设施验证测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta
from storage.models import SocialPost, SentimentResult, StockSentimentAggregate, StockCandidate, DailyRecommendation
from storage.sqlite_store import SentimentStore


def test_models():
    """测试数据模型"""
    print("=== 测试数据模型 ===")

    # SocialPost
    post = SocialPost(
        source='eastmoney', stock_code='600519', stock_name='贵州茅台',
        title='茅台明天会涨吗？', content='感觉明天要涨停',
        author='散户小王', publish_time=datetime.now(),
        read_count=1000, comment_count=50, like_count=20
    )
    assert post.text == '感觉明天要涨停'
    assert post.engagement_score == 1000 * 0.1 + 50 * 3 + 20 * 2  # 290
    assert post.crawl_time is not None
    print(f"  SocialPost: OK (engagement={post.engagement_score})")

    # 无content时text返回title
    post2 = SocialPost(
        source='xueqiu', stock_code='000001', stock_name='平安银行',
        title='平安银行被低估了', content='',
        author='大V', publish_time=datetime.now()
    )
    assert post2.text == '平安银行被低估了'
    print(f"  SocialPost (no content): OK (text={post2.text})")

    # SentimentResult
    result = SentimentResult(
        stock_code='600519', source='eastmoney', method='snownlp',
        raw_score=0.85, normalized_score=0.7, confidence=0.8
    )
    assert result.timestamp is not None
    print(f"  SentimentResult: OK (score={result.normalized_score})")

    # StockSentimentAggregate
    agg = StockSentimentAggregate(
        stock_code='600519', stock_name='贵州茅台',
        date='2026-03-26', source='combined',
        comment_volume=100, avg_sentiment=0.65,
        bullish_ratio=0.72, disagreement_index=0.15,
        score=78.5
    )
    print(f"  StockSentimentAggregate: OK (score={agg.score})")

    # StockCandidate
    candidate = StockCandidate(
        stock_code='600519', stock_name='贵州茅台',
        price=1800, market_cap=150, turnover_rate=1.5,
        technical_score=70, capital_score=65,
        sentiment_score=80, risk_adjustment=-5,
        total_score=72.5, signal='BUY',
        reason='情绪持续走强'
    )
    print(f"  StockCandidate: OK (total={candidate.total_score}, signal={candidate.signal})")

    # DailyRecommendation
    rec = DailyRecommendation(
        date='2026-03-26', stock_code='600519', stock_name='贵州茅台',
        signal='BUY', entry_price=1800, total_score=72.5, sentiment_score=80
    )
    print(f"  DailyRecommendation: OK")
    print("=== 数据模型测试通过 ===\n")


def test_sqlite_store():
    """测试SQLite存储"""
    print("=== 测试SQLite存储 ===")

    # 使用临时数据库
    test_db = "/tmp/test_sentiment.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    store = SentimentStore(test_db)
    print(f"  数据库创建: OK ({test_db})")

    # 1. 保存帖子
    posts = [
        SocialPost(
            source='eastmoney', stock_code='600519', stock_name='贵州茅台',
            title='茅台明天看涨', content='',
            author='user1', publish_time=datetime.now(),
            url='https://guba.eastmoney.com/1'
        ),
        SocialPost(
            source='eastmoney', stock_code='600519', stock_name='贵州茅台',
            title='茅台要跌了吧', content='感觉不妙',
            author='user2', publish_time=datetime.now(),
            url='https://guba.eastmoney.com/2'
        ),
        SocialPost(
            source='xueqiu', stock_code='600519', stock_name='贵州茅台',
            title='茅台基本面分析', content='从估值角度看...',
            author='大V李', publish_time=datetime.now(),
            url='https://xueqiu.com/post/3',
            author_followers=50000
        ),
    ]
    saved = store.save_posts(posts)
    print(f"  保存帖子: {saved} 条新增")

    # 2. 去重测试
    saved2 = store.save_posts(posts[:1])  # 重复保存第一条
    print(f"  去重测试: {saved2} 条新增（应为0）")

    # 3. 查询帖子
    fetched = store.get_posts('600519', source='eastmoney')
    assert len(fetched) == 2, f"期望2条，实际{len(fetched)}条"
    print(f"  查询帖子(eastmoney): {len(fetched)} 条")

    fetched_all = store.get_posts('600519')
    assert len(fetched_all) == 3, f"期望3条，实际{len(fetched_all)}条"
    print(f"  查询帖子(all): {len(fetched_all)} 条")

    count = store.get_post_count('600519')
    assert count == 3
    print(f"  帖子计数: {count}")

    # 4. 情绪分数
    agg = StockSentimentAggregate(
        stock_code='600519', stock_name='贵州茅台',
        date='2026-03-26', source='eastmoney',
        comment_volume=2, avg_sentiment=0.55,
        bullish_ratio=0.5, disagreement_index=0.35,
        score=62.0
    )
    store.save_sentiment_aggregate(agg)
    print(f"  保存情绪分数: OK")

    loaded = store.get_sentiment('600519', '2026-03-26', 'eastmoney')
    assert loaded is not None
    assert loaded.score == 62.0
    print(f"  查询情绪分数: score={loaded.score}")

    # 5. 推荐记录
    rec = DailyRecommendation(
        date='2026-03-26', stock_code='600519', stock_name='贵州茅台',
        signal='BUY', entry_price=1800, total_score=72.5, sentiment_score=80
    )
    store.save_recommendation(rec)
    print(f"  保存推荐: OK")

    positions = store.get_open_positions()
    assert len(positions) == 1
    assert positions[0].stock_code == '600519'
    print(f"  未平仓查询: {len(positions)} 条")

    # 更新平仓
    store.update_exit('2026-03-26', '600519', '2026-03-28', 1850, 2.78, '止盈')
    positions2 = store.get_open_positions()
    assert len(positions2) == 0
    print(f"  平仓更新后: {len(positions2)} 条未平仓")

    # 6. 统计
    stats = store.get_stats()
    print(f"  数据库统计: {stats}")

    # 清理
    os.remove(test_db)
    print("=== SQLite存储测试通过 ===\n")


def test_base_source():
    """测试爬虫基类"""
    print("=== 测试爬虫基类 ===")

    from social.base_source import BaseSocialSource

    class MockSource(BaseSocialSource):
        def __init__(self):
            super().__init__('mock', min_interval=0.1)
            self.call_count = 0

        def fetch_stock_posts(self, stock_code, stock_name="", limit=30):
            self.call_count += 1
            return [SocialPost(
                source='mock', stock_code=stock_code, stock_name=stock_name,
                title=f'Mock post for {stock_code}', content='',
                author='bot', publish_time=datetime.now(),
                url=f'mock://{stock_code}/{self.call_count}'
            )]

        def health_check(self):
            return True

    source = MockSource()
    assert source.health_check()
    print(f"  health_check: OK")

    # 单只股票
    posts = source.fetch_stock_posts('600519', '贵州茅台')
    assert len(posts) == 1
    assert posts[0].stock_code == '600519'
    print(f"  fetch_stock_posts: OK ({len(posts)} post)")

    # 批量
    stocks = [
        {'code': '600519', 'name': '贵州茅台'},
        {'code': '000001', 'name': '平安银行'},
        {'code': '300750', 'name': '宁德时代'},
    ]
    results = source.fetch_batch(stocks, limit_per_stock=1)
    assert len(results) == 3
    assert all(len(v) == 1 for v in results.values())
    print(f"  fetch_batch: OK ({len(results)} stocks)")

    # UA轮换
    uas = set(source._get_random_ua() for _ in range(20))
    assert len(uas) > 1
    print(f"  UA轮换: OK ({len(uas)} unique UAs)")

    # Headers
    headers = source._build_headers({'Referer': 'https://example.com'})
    assert 'User-Agent' in headers
    assert headers['Referer'] == 'https://example.com'
    print(f"  headers构建: OK")

    print("=== 爬虫基类测试通过 ===\n")


def test_config():
    """测试配置"""
    print("=== 测试配置 ===")
    import config

    assert config.SCORE_WEIGHTS['technical'] == 0.30
    assert config.SCORE_WEIGHTS['sentiment'] == 0.40
    assert abs(sum(config.SCORE_WEIGHTS.values()) - 1.0) < 0.001
    print(f"  评分权重: {config.SCORE_WEIGHTS} (sum=1.0)")

    assert abs(sum(config.SENTIMENT_SUB_WEIGHTS.values()) - 1.0) < 0.001
    print(f"  情绪子权重: {config.SENTIMENT_SUB_WEIGHTS} (sum=1.0)")

    assert abs(sum(s['weight'] for s in config.SOCIAL_SOURCES.values()) - 1.0) < 0.001
    weights_str = ', '.join(f"{k}={v['weight']}" for k, v in config.SOCIAL_SOURCES.items())
    print(f"  数据源权重: {weights_str} (sum=1.0)")

    assert config.STOCK_FILTER['min_market_cap'] == 10
    assert config.STOCK_FILTER['max_market_cap'] == 200
    print(f"  股票筛选: 市值{config.STOCK_FILTER['min_market_cap']}-{config.STOCK_FILTER['max_market_cap']}亿")
    print(f"  LLM模型: {config.LLM_MODEL}")
    print("=== 配置测试通过 ===\n")


if __name__ == '__main__':
    test_models()
    test_sqlite_store()
    test_base_source()
    test_config()
    print("=" * 50)
    print("Phase 0 所有测试通过！基础设施就绪。")
    print("=" * 50)
