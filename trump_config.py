"""
Trump Social Media -> Polymarket Trading Signal System
配置模块
"""

import os

# ============================================================
# 社交媒体监控
# ============================================================

# Twitter/X API
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
TRUMP_TWITTER_USER_ID = "25073877"  # @realDonaldTrump numeric ID
TRUMP_TWITTER_USERNAME = "realDonaldTrump"

# Truth Social
TRUTH_SOCIAL_USERNAME = "realDonaldTrump"
TRUTH_SOCIAL_BASE_URL = "https://truthsocial.com"

# 轮询间隔（秒）
POLL_INTERVAL = 30

# Playwright浏览器设置
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

# ============================================================
# LLM分析（Kimi API - OpenAI兼容格式）
# ============================================================

KIMI_API_KEY = os.getenv("KIMI_API_KEY", "sk-kimi-e54HLtfDf4T0Mei4nxcZt7l14vQMG9QigQPaeL1vmjdyTc5GT3wMXwOqsEaKISGk")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.kimi.com/coding/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-for-coding")

# 可影响Polymarket的主题类别
TOPIC_CATEGORIES = [
    "tariffs_trade",        # 关税、贸易战、贸易协议
    "crypto_digital",       # 比特币、加密货币监管、CBDC
    "foreign_policy",       # 中国、俄罗斯、乌克兰、NATO、制裁
    "election_politics",    # 选举、候选人、竞选
    "economy_fiscal",       # 税收、支出、债务上限、美联储
    "regulation_policy",    # 行政令、监管变化
    "personnel",            # 内阁人选、解雇、任命
    "legal_judicial",       # 法院案件、调查、赦免
    "military_defense",     # 军事行动、国防开支
    "tech_social_media",    # TikTok、大科技、Section 230
]

# ============================================================
# Polymarket
# ============================================================

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB_API = "https://clob.polymarket.com"

# 第二阶段：交易凭证
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_SECRET = os.getenv("POLYMARKET_SECRET", "")
POLYMARKET_PASSPHRASE = os.getenv("POLYMARKET_PASSPHRASE", "")

# 交易参数
MAX_POSITION_SIZE_USDC = 50  # 单笔最大仓位
MIN_CONFIDENCE_THRESHOLD = 60  # 生成信号的最低置信度%
MAX_DAILY_TRADES = 10

# ============================================================
# 邮件通知（QQ邮箱SMTP）
# ============================================================

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "fyf1028@qq.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "pkrbqgunhnlabhhh")
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS", "fyf1028@126.com").split(",")

# ============================================================
# 状态管理
# ============================================================

POST_STORE_FILE = os.getenv("POST_STORE_FILE", "data/seen_posts.json")
MAX_STORED_POSTS = 1000  # 保留最近N条推文用于去重

# ============================================================
# 日志
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
