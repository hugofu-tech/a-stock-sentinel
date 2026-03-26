"""Phase 1 集成测试 — 验证所有模块能正常协作"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from storage.models import SocialPost, StockSentimentAggregate
from storage.sqlite_store import SentimentStore
from nlp.snownlp_analyzer import SnowNLPAnalyzer
from nlp.sentiment_scorer import SentimentScorer
from social.base_source import BaseSocialSource


def create_mock_posts(stock_code, stock_name, sentiments):
    """创建模拟帖子数据"""
    posts = []
    for i, (title, is_positive) in enumerate(sentiments):
        posts.append(SocialPost(
            source='eastmoney',
            stock_code=stock_code,
            stock_name=stock_name,
            title=title,
            content='',
            author=f'user_{i}',
            publish_time=datetime.now() - timedelta(hours=i),
            url=f'https://guba.eastmoney.com/mock/{stock_code}/{i}',
            read_count=100 + i * 50,
            comment_count=10 + i * 5,
            like_count=5 + i * 2,
        ))
    return posts


def test_snownlp_integration():
    """测试 SnowNLP 分析器完整流程"""
    print("=== 测试 SnowNLP 集成 ===")

    analyzer = SnowNLPAnalyzer()

    # 模拟看多帖子
    bullish_posts = create_mock_posts('600519', '贵州茅台', [
        ('茅台明天肯定涨停，太牛了！', True),
        ('贵州茅台业绩大增，强烈看好！', True),
        ('茅台价值被严重低估，坚决看多', True),
        ('白酒龙头，长期持有必赚', True),
        ('茅台今天表现不好，但没关系', False),
    ])

    # 分析帖子
    results = analyzer.analyze_posts(bullish_posts)
    assert len(results) == 5, f"期望5条结果，实际{len(results)}"
    print(f"  分析结果: {len(results)} 条")
    for r in results:
        print(f"    raw={r.raw_score:.3f} normalized={r.normalized_score:.3f} confidence={r.confidence:.3f}")

    # 聚合
    agg = analyzer.aggregate_sentiment(
        stock_code='600519', stock_name='贵州茅台',
        date='2026-03-26', source='eastmoney',
        posts=bullish_posts, results=results
    )
    assert 0 <= agg.score <= 100
    print(f"  聚合结果: avg_sentiment={agg.avg_sentiment:.3f}, "
          f"bullish_ratio={agg.bullish_ratio:.2f}, "
          f"disagreement={agg.disagreement_index:.3f}, "
          f"score={agg.score:.1f}")

    # 模拟看空帖子
    bearish_posts = create_mock_posts('000001', '平安银行', [
        ('平安银行要完蛋了，赶紧跑', False),
        ('银行股不行了，别买了', False),
        ('平安银行管理层太差，坚决看空', False),
    ])
    results_bear = analyzer.analyze_posts(bearish_posts)
    agg_bear = analyzer.aggregate_sentiment(
        stock_code='000001', stock_name='平安银行',
        date='2026-03-26', source='eastmoney',
        posts=bearish_posts, results=results_bear
    )
    print(f"  看空股: avg_sentiment={agg_bear.avg_sentiment:.3f}, "
          f"score={agg_bear.score:.1f}")

    # 看多应该得分高于看空
    assert agg.score > agg_bear.score, "看多得分应高于看空"
    print(f"  看多({agg.score:.1f}) > 看空({agg_bear.score:.1f}): OK")
    print("=== SnowNLP 集成测试通过 ===\n")
    return agg, agg_bear


def test_sentiment_scorer(agg_bull, agg_bear):
    """测试情绪评分器"""
    print("=== 测试情绪评分器 ===")

    scorer = SentimentScorer()

    # 多源合并（模拟两个源）
    sources = {
        'eastmoney': agg_bull,
        'xueqiu': StockSentimentAggregate(
            stock_code='600519', stock_name='贵州茅台',
            date='2026-03-26', source='xueqiu',
            comment_volume=15, avg_sentiment=0.5,
            bullish_ratio=0.7, disagreement_index=0.2,
            score=70
        )
    }
    combined = scorer.combine_sources(sources)
    assert combined.source == 'combined'
    print(f"  多源合并: avg_sentiment={combined.avg_sentiment:.3f}, "
          f"comment_volume={combined.comment_volume}")

    # 最终评分
    score = scorer.calculate_sentiment_score(combined)
    assert 0 <= score <= 100
    print(f"  最终评分: {score:.1f}")

    # 异常检测
    anomalies = scorer.detect_anomalies(combined, [])
    print(f"  异常检测: {anomalies}")

    # 排名
    stock_scores = {'600519': 78.5, '000001': 45.2, '300750': 82.1}
    ranked = scorer.rank_stocks(stock_scores)
    assert ranked[0][0] == '300750'  # 最高分排第一
    print(f"  排名: {ranked}")

    print("=== 情绪评分器测试通过 ===\n")


def test_storage_integration():
    """测试存储集成"""
    print("=== 测试存储集成 ===")

    test_db = "/tmp/test_phase1_integration.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    store = SentimentStore(test_db)

    # 保存帖子
    posts = create_mock_posts('600519', '贵州茅台', [
        ('茅台很棒', True),
        ('继续看好', True),
    ])
    saved = store.save_posts(posts)
    print(f"  保存帖子: {saved}")

    # 保存情绪分数
    agg = StockSentimentAggregate(
        stock_code='600519', stock_name='贵州茅台',
        date='2026-03-26', source='combined',
        comment_volume=20, avg_sentiment=0.6,
        bullish_ratio=0.75, disagreement_index=0.15,
        score=78.5
    )
    store.save_sentiment_aggregate(agg)

    # 读取验证
    loaded = store.get_sentiment('600519', '2026-03-26', 'combined')
    assert loaded is not None
    assert loaded.score == 78.5
    print(f"  存取验证: score={loaded.score}")

    # 清理
    os.remove(test_db)
    print("=== 存储集成测试通过 ===\n")


def test_backtest_engine():
    """测试回测引擎"""
    print("=== 测试回测引擎 ===")

    from backtest.engine import BacktestEngine
    from backtest.metrics import calculate_metrics

    engine = BacktestEngine()

    # 创建模拟价格数据
    dates = pd.date_range('2026-01-05', '2026-03-25', freq='B')  # 工作日
    price_rows = []
    np.random.seed(42)
    base_price = 50.0
    for date in dates:
        price = base_price * (1 + np.random.normal(0, 0.02))
        base_price = price
        price_rows.append({
            'date': date.strftime('%Y-%m-%d'),
            'stock_code': '600519',
            'open': round(price * 0.998, 2),
            'high': round(price * 1.02, 2),
            'low': round(price * 0.98, 2),
            'close': round(price, 2),
            'volume': 100000,
        })
    price_data = pd.DataFrame(price_rows)

    # 创建模拟信号
    signal_dates = ['2026-01-12', '2026-02-03', '2026-02-24']
    signals = [
        {'date': d, 'stock_code': '600519', 'stock_name': '贵州茅台',
         'score': 80, 'signal': 'BUY'}
        for d in signal_dates
    ]

    # 运行回测
    result = engine.run(signals, price_data, '2026-01-05', '2026-03-25')
    print(f"  交易数: {len(result['trades'])}")
    print(f"  指标: {result['metrics']}")

    # 验证指标格式
    m = result['metrics']
    assert 'total_return' in m
    assert 'sharpe_ratio' in m
    assert 'max_drawdown' in m
    assert 'win_rate' in m
    assert 'total_trades' in m
    print(f"  总收益: {m['total_return']:.2f}%")
    print(f"  胜率: {m['win_rate']:.2f}%")

    # 打印回测摘要
    engine.print_summary(result)
    print("=== 回测引擎测试通过 ===\n")


if __name__ == '__main__':
    agg_bull, agg_bear = test_snownlp_integration()
    test_sentiment_scorer(agg_bull, agg_bear)
    test_storage_integration()
    test_backtest_engine()
    print("=" * 50)
    print("Phase 1 集成测试全部通过！")
    print("=" * 50)
