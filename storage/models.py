"""数据模型定义 — 社交媒体情绪选股系统"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SocialPost:
    """社交媒体帖子"""
    source: str              # eastmoney / xueqiu / weibo / shizifengyun
    stock_code: str          # 股票代码，如 '600519'
    stock_name: str          # 股票名称，如 '贵州茅台'
    title: str               # 帖子标题
    content: str             # 帖子内容（可为空，有些只取标题）
    author: str              # 作者
    publish_time: datetime   # 发布时间
    url: str = ""            # 帖子URL
    read_count: int = 0      # 阅读数
    comment_count: int = 0   # 评论数
    like_count: int = 0      # 点赞数
    author_followers: int = 0  # 作者粉丝数（雪球用）
    crawl_time: Optional[datetime] = None  # 抓取时间

    def __post_init__(self):
        if self.crawl_time is None:
            self.crawl_time = datetime.now()

    @property
    def text(self) -> str:
        """用于NLP分析的文本：优先使用content，否则用title"""
        return self.content if self.content else self.title

    @property
    def engagement_score(self) -> float:
        """互动分数，用于加权"""
        return (self.read_count * 0.1 + self.comment_count * 3 +
                self.like_count * 2)


@dataclass
class SentimentResult:
    """单条帖子的情绪分析结果"""
    stock_code: str
    source: str              # 数据源
    method: str              # snownlp / llm
    raw_score: float         # 原始分数 [0, 1]（SnowNLP）或 [-1, 1]（LLM）
    normalized_score: float  # 标准化分数 [-1, 1]，-1极度看空，+1极度看多
    confidence: float        # 置信度 [0, 1]
    post_url: str = ""       # 对应帖子URL
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class StockSentimentAggregate:
    """单只股票的聚合情绪数据（某日某源或综合）"""
    stock_code: str
    stock_name: str
    date: str                   # YYYY-MM-DD
    source: str                 # eastmoney/xueqiu/weibo/shizifengyun/combined
    comment_volume: int = 0     # 评论/帖子总数
    avg_sentiment: float = 0.0  # 平均情绪 [-1, 1]
    bullish_ratio: float = 0.0  # 看多比例 [0, 1]
    disagreement_index: float = 0.0  # 分歧度（标准差）
    sentiment_change: float = 0.0    # 情绪变化率（较前一日）
    volume_change: float = 0.0       # 评论量变化率
    weighted_sentiment: float = 0.0  # 加权情绪（按互动/粉丝加权）
    score: float = 0.0               # 最终情绪评分 [0, 100]


@dataclass
class StockCandidate:
    """候选股票（用于最终推荐）"""
    stock_code: str
    stock_name: str
    price: float = 0.0
    change_pct: float = 0.0           # 涨跌幅%
    market_cap: float = 0.0           # 流通市值（亿）
    turnover_rate: float = 0.0        # 换手率%
    volume_ratio: float = 0.0         # 量比

    # 评分维度
    technical_score: float = 0.0      # 技术面 [0, 100]
    capital_score: float = 0.0        # 资金面 [0, 100]
    sentiment_score: float = 0.0      # 社交情绪 [0, 100]
    risk_adjustment: float = 0.0      # 风险调整 [-20, 0]
    total_score: float = 0.0          # 总分 [0, 100]

    # 情绪细节
    sentiment_details: dict = field(default_factory=dict)
    # e.g. {'eastmoney': 72, 'xueqiu': 68, 'weibo': 55, 'combined': 65}

    signal: str = ""                  # BUY / SELL / WATCH
    reason: str = ""                  # 推荐理由
    llm_summary: str = ""             # LLM分析摘要
    suggested_hold_days: int = 0      # 建议持有天数
    stop_loss_pct: float = -5.0       # 止损线%
    take_profit_pct: float = 10.0     # 止盈线%


@dataclass
class DailyRecommendation:
    """每日推荐记录（用于回测和追踪）"""
    date: str                    # 推荐日期 YYYY-MM-DD
    stock_code: str
    stock_name: str
    signal: str                  # BUY / SELL
    entry_price: float = 0.0    # 推荐时价格
    total_score: float = 0.0
    sentiment_score: float = 0.0
    exit_date: str = ""          # 实际退出日期
    exit_price: float = 0.0     # 退出价格
    return_pct: float = 0.0     # 收益率%
    exit_reason: str = ""       # 退出原因
