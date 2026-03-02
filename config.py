# A股情绪晨间预警系统 - 配置

import os

# 飞书配置
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# 发送时间配置（24小时制）
SEND_HOUR = 9
SEND_MINUTE = 15

# 情绪指数阈值
SENTIMENT_THRESHOLDS = {
    "extreme_fear": 20,    # 极度恐慌上限
    "fear": 40,            # 恐慌上限
    "neutral": 60,         # 中性上限
    "greed": 80,           # 贪婪上限
}

# 板块数量配置
TOP_SECTORS_COUNT = 5

# 日志配置
LOG_LEVEL = "INFO"
LOG_FILE = "logs/sentinel.log"

# 缓存配置（避免重复请求）
CACHE_TTL = 300  # 5分钟
