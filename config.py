# A股情绪选股系统 - 配置
# 原有配置保留，新增社交媒体情绪选股相关配置

import os

# ============================================================
# 飞书配置（原有）
# ============================================================
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# ============================================================
# 邮件配置（新增）
# ============================================================
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.qq.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # QQ邮箱授权码
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "").split(",")  # 逗号分隔的收件人

# ============================================================
# LLM配置（Kimi K2.5）
# ============================================================
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.kimi.com/coding/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "kimi-k2.5")

# ============================================================
# 发送时间配置（24小时制，北京时间）
# ============================================================
SEND_HOUR = 9
SEND_MINUTE = 15

# ============================================================
# 社交媒体数据源配置
# ============================================================
SOCIAL_SOURCES = {
    'eastmoney': {
        'enabled': True,
        'weight': 0.35,         # 评分权重
        'min_interval': 2.0,    # 请求最小间隔（秒）
        'max_retries': 3,
        'timeout': 15,
        'posts_per_stock': 20,  # 每只股票采集帖子数
    },
    'xueqiu': {
        'enabled': True,
        'weight': 0.30,
        'min_interval': 3.0,    # 雪球更严格
        'max_retries': 3,
        'timeout': 15,
        'posts_per_stock': 20,
    },
    'weibo': {
        'enabled': True,
        'weight': 0.20,
        'min_interval': 2.0,
        'max_retries': 3,
        'timeout': 15,
        'posts_per_stock': 15,
    },
    'shizifengyun': {
        'enabled': True,
        'weight': 0.15,
        'min_interval': 2.0,
        'max_retries': 3,
        'timeout': 15,
        'posts_per_stock': 10,
    },
}

# ============================================================
# NLP情绪分析配置
# ============================================================
NLP_CONFIG = {
    'bulk_method': 'snownlp',      # 批量分析方法
    'validation_method': 'llm',    # 精选验证方法
    'llm_top_n': 10,               # LLM验证Top N候选
    'bullish_threshold': 0.6,      # SnowNLP看多阈值
    'bearish_threshold': 0.4,      # SnowNLP看空阈值
}

# ============================================================
# 股票筛选配置
# ============================================================
STOCK_FILTER = {
    'min_market_cap': 10,          # 流通市值下限（亿）
    'max_market_cap': 200,         # 流通市值上限（亿）
    'min_turnover_avg10': 3.0,     # 10日均换手率下限(%)
    'max_turnover_avg10': 45.0,    # 10日均换手率上限(%)
    'exclude_st': True,            # 排除ST股
    'exclude_limit_up': True,      # 排除当日涨停
    'exclude_new_stock_days': 30,  # 排除上市不满N天的次新股
    'min_price': 2.0,              # 最低股价
    'max_price': 200.0,            # 最高股价
    'min_social_posts_24h': 5,     # 24h内最少社交帖子数
}

# ============================================================
# 评分模型权重
# ============================================================
SCORE_WEIGHTS = {
    'technical': 0.30,             # 技术面
    'capital': 0.20,               # 资金面
    'sentiment': 0.40,             # 社交情绪
    'risk_adjustment': 0.10,       # 风险调整
}

# 社交情绪评分细分权重（在sentiment 40%内部的分配）
SENTIMENT_SUB_WEIGHTS = {
    'polarity': 0.375,             # 情绪极性 (15% / 40%)
    'momentum': 0.250,             # 情绪动量 (10% / 40%)
    'volume_surge': 0.200,         # 评论量异常 (8% / 40%)
    'llm_quality': 0.175,          # LLM验证 (7% / 40%)
}

# ============================================================
# 交易策略配置
# ============================================================
TRADING_CONFIG = {
    'max_buy_recommendations': 3,   # 每日最多买入推荐
    'max_sell_recommendations': 3,   # 每日最多卖出推荐
    'default_hold_days': 3,         # 默认持有天数
    'stop_loss_pct': -5.0,          # 止损线(%)
    'take_profit_pct': 10.0,        # 止盈线(%)
    'sentiment_reversal_threshold': -0.30,  # 情绪反转卖出阈值
    'entry_time': '09:30',          # 入场时间
    'avoid_gap_up_pct': 3.0,        # 避免跳空高开超过N%的股票
}

# ============================================================
# 回测配置
# ============================================================
BACKTEST_CONFIG = {
    'commission_rate': 0.0003,      # 佣金费率（万三）
    'stamp_tax_rate': 0.001,        # 印花税（千一，卖出时收取）
    'slippage_pct': 0.001,          # 滑点（千一）
    'initial_capital': 100000,      # 初始资金（元）
    'benchmark': '000300',          # 基准指数（沪深300）
}

# ============================================================
# 情绪指数阈值（原有，保留兼容）
# ============================================================
SENTIMENT_THRESHOLDS = {
    "extreme_fear": 20,
    "fear": 40,
    "neutral": 60,
    "greed": 80,
}

# ============================================================
# 其他配置
# ============================================================
TOP_SECTORS_COUNT = 5
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = "logs/sentinel.log"
CACHE_TTL = 300  # 5分钟
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "sentiment.db")
