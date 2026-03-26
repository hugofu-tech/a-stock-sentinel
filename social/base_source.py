"""社交媒体数据源抽象基类"""

import time
import random
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

from storage.models import SocialPost

logger = logging.getLogger(__name__)


class BaseSocialSource(ABC):
    """所有社交媒体数据源的基类

    内置功能：
    - Rate limiting（请求间隔控制）
    - 指数退避重试
    - User-Agent轮换
    - 批量采集编排
    """

    # 常用User-Agent列表，子类可覆盖
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]

    def __init__(self, name: str, min_interval: float = 2.0,
                 max_retries: int = 3, timeout: int = 15):
        """
        Args:
            name: 数据源名称（eastmoney/xueqiu/weibo/shizifengyun）
            min_interval: 请求最小间隔（秒）
            max_retries: 最大重试次数
            timeout: 请求超时时间（秒）
        """
        self.name = name
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_request_time = 0.0

    @abstractmethod
    def fetch_stock_posts(self, stock_code: str, stock_name: str = "",
                          limit: int = 30) -> List[SocialPost]:
        """获取指定股票的帖子列表

        Args:
            stock_code: 股票代码（纯数字，如 '600519'）
            stock_name: 股票名称
            limit: 最多获取条数
        Returns:
            帖子列表
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """检查数据源是否可用"""
        ...

    def fetch_batch(self, stocks: List[Dict[str, str]],
                    limit_per_stock: int = 20) -> Dict[str, List[SocialPost]]:
        """批量获取多只股票的帖子

        Args:
            stocks: [{'code': '600519', 'name': '贵州茅台'}, ...]
            limit_per_stock: 每只股票最多获取条数
        Returns:
            {stock_code: [posts]}
        """
        results = {}
        total = len(stocks)
        for i, stock in enumerate(stocks):
            code = stock['code']
            name = stock.get('name', '')
            try:
                self._rate_limit()
                posts = self.fetch_stock_posts(code, name, limit_per_stock)
                results[code] = posts
                if (i + 1) % 50 == 0:
                    logger.info(f"[{self.name}] 进度: {i+1}/{total}, "
                                f"已获取 {sum(len(v) for v in results.values())} 条帖子")
            except Exception as e:
                logger.warning(f"[{self.name}] 获取 {code} {name} 失败: {e}")
                results[code] = []
        logger.info(f"[{self.name}] 批量采集完成: {total}只股票, "
                    f"{sum(len(v) for v in results.values())}条帖子")
        return results

    def _rate_limit(self):
        """请求间隔控制"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_interval:
            jitter = random.uniform(0, self.min_interval * 0.3)
            sleep_time = self.min_interval - elapsed + jitter
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _get_random_ua(self) -> str:
        """随机获取User-Agent"""
        return random.choice(self.USER_AGENTS)

    def _retry_request(self, func, *args, **kwargs):
        """带指数退避的重试机制

        Args:
            func: 要重试的函数
        Returns:
            函数返回值
        Raises:
            最后一次异常
        """
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"[{self.name}] 请求失败(第{attempt+1}次): {e}, "
                                   f"{wait:.1f}秒后重试")
                    time.sleep(wait)
        raise last_error

    def _build_headers(self, extra: dict = None) -> dict:
        """构建请求头"""
        headers = {
            'User-Agent': self._get_random_ua(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        if extra:
            headers.update(extra)
        return headers
