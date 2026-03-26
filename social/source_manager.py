"""多数据源编排管理器

统一管理所有社交媒体数据源（东方财富、雪球、微博、市值风云），
提供健康检查、批量采集、权重归一化等功能，支持优雅降级。
"""

import time
import logging
from typing import Dict, List, Optional

from storage.models import SocialPost
import config

logger = logging.getLogger(__name__)

# How often to re-check unhealthy sources (in seconds).
_HEALTH_RECHECK_INTERVAL = 30 * 60  # 30 minutes

# 数据源名称到模块/类的映射
_SOURCE_REGISTRY = {
    'eastmoney': ('social.eastmoney_guba', 'EastMoneyGuba'),
    'xueqiu': ('social.xueqiu_crawler', 'XueqiuCrawler'),
    'weibo': ('social.weibo_stock', 'WeiboStock'),
    'shizifengyun': ('social.shizifengyun', 'ShizifengyunCrawler'),
}


class SourceManager:
    """多数据源编排管理器

    根据config中的SOCIAL_SOURCES配置初始化所有启用的数据源，
    提供统一的健康检查、批量采集、权重管理接口。
    当某个数据源模块不存在或初始化失败时，自动跳过该数据源。
    """

    def __init__(self):
        """初始化所有启用的数据源"""
        self.sources = {}           # name -> source instance
        self.source_configs = {}    # name -> config dict
        self._health_status = {}    # name -> bool (最近一次健康检查结果)
        self._health_check_time = {}  # name -> float (上次健康检查时间戳)
        self._post_counts = {}     # name -> int (累计采集帖子数)

        source_configs = getattr(config, 'SOCIAL_SOURCES', {})

        for name, src_config in source_configs.items():
            if not src_config.get('enabled', False):
                logger.info(f"[SourceManager] 数据源 '{name}' 已禁用，跳过")
                continue

            self.source_configs[name] = src_config

            if name not in _SOURCE_REGISTRY:
                logger.warning(
                    f"[SourceManager] 未知数据源 '{name}'，跳过"
                )
                continue

            module_path, class_name = _SOURCE_REGISTRY[name]
            try:
                module = __import__(module_path, fromlist=[class_name])
                cls = getattr(module, class_name)
                instance = cls(
                    min_interval=src_config.get('min_interval', 2.0),
                    max_retries=src_config.get('max_retries', 3),
                    timeout=src_config.get('timeout', 15),
                )
                self.sources[name] = instance
                self._post_counts[name] = 0
                logger.info(f"[SourceManager] 数据源 '{name}' 初始化成功")
            except ImportError as e:
                logger.warning(
                    f"[SourceManager] 数据源 '{name}' 模块导入失败: {e}，跳过"
                )
            except Exception as e:
                logger.warning(
                    f"[SourceManager] 数据源 '{name}' 初始化失败: {e}，跳过"
                )

        logger.info(
            f"[SourceManager] 初始化完成，"
            f"已加载 {len(self.sources)}/{len(source_configs)} 个数据源: "
            f"{list(self.sources.keys())}"
        )

    def check_health(self) -> Dict[str, bool]:
        """对所有已加载的数据源执行健康检查

        Returns:
            {source_name: is_healthy}
        """
        now = time.time()

        for name, source in self.sources.items():
            try:
                healthy = source.health_check()
                self._health_status[name] = healthy
                self._health_check_time[name] = now
                status_str = "通过" if healthy else "未通过"
                logger.info(f"[SourceManager] {name} 健康检查{status_str}")
            except Exception as e:
                self._health_status[name] = False
                self._health_check_time[name] = now
                logger.warning(
                    f"[SourceManager] {name} 健康检查异常: {e}"
                )

        passed = sum(1 for v in self._health_status.values() if v)
        total = len(self._health_status)
        logger.info(
            f"[SourceManager] 健康检查完成: {passed}/{total} 个数据源可用"
        )

        return dict(self._health_status)

    def _recheck_unhealthy_sources(self):
        """对之前不健康的数据源进行周期性重新检查

        如果距离上次检查超过 _HEALTH_RECHECK_INTERVAL（30分钟），
        则重新对不健康的数据源执行健康检查，恢复可用的源。
        """
        now = time.time()
        rechecked = []

        for name, source in self.sources.items():
            # Only re-check sources that are currently unhealthy
            if self._health_status.get(name, False):
                continue

            last_check = self._health_check_time.get(name, 0.0)
            if now - last_check < _HEALTH_RECHECK_INTERVAL:
                continue

            logger.info(
                f"[SourceManager] 重新检查不健康数据源: {name} "
                f"(距上次检查 {int((now - last_check) / 60)} 分钟)"
            )
            try:
                healthy = source.health_check()
                self._health_status[name] = healthy
                self._health_check_time[name] = now
                rechecked.append(name)
                if healthy:
                    logger.info(
                        f"[SourceManager] {name} 已恢复健康!"
                    )
                else:
                    logger.info(
                        f"[SourceManager] {name} 仍然不健康，"
                        f"将在 {_HEALTH_RECHECK_INTERVAL // 60} 分钟后再试"
                    )
            except Exception as e:
                self._health_status[name] = False
                self._health_check_time[name] = now
                rechecked.append(name)
                logger.warning(
                    f"[SourceManager] {name} 重新检查异常: {e}"
                )

        if rechecked:
            recovered = [
                n for n in rechecked if self._health_status.get(n, False)
            ]
            if recovered:
                logger.info(
                    f"[SourceManager] 恢复的数据源: {recovered}"
                )

    def fetch_all_posts(
        self,
        stocks: List[Dict],
        limit_per_stock: int = 20,
    ) -> Dict[str, Dict[str, List[SocialPost]]]:
        """从所有可用数据源批量采集帖子

        Args:
            stocks: 股票列表，每项为 {'code': '600519', 'name': '贵州茅台'}
            limit_per_stock: 每只股票每个数据源最多获取条数

        Returns:
            {source_name: {stock_code: [SocialPost, ...]}}
            外层键为数据源名称，内层键为股票代码
        """
        all_results: Dict[str, Dict[str, List[SocialPost]]] = {}

        # Before fetching, re-check any previously unhealthy sources
        # that haven't been checked in the last 30 minutes.
        self._recheck_unhealthy_sources()

        for name, source in self.sources.items():
            # 跳过健康检查未通过的数据源
            if self._health_status.get(name) is False:
                logger.info(f"[SourceManager] 跳过 {name}（健康检查未通过）")
                all_results[name] = {}
                continue

            src_config = self.source_configs.get(name, {})
            per_stock = src_config.get('posts_per_stock', limit_per_stock)

            logger.info(
                f"[SourceManager] 开始采集 {name}，"
                f"共 {len(stocks)} 只股票，每只最多 {per_stock} 条"
            )

            try:
                # 使用基类的 fetch_batch 方法（内置rate limiting和错误处理）
                source_results = source.fetch_batch(stocks, per_stock)
                all_results[name] = source_results

                # 统计本次采集数量
                count = sum(len(posts) for posts in source_results.values())
                self._post_counts[name] = self._post_counts.get(name, 0) + count
                logger.info(
                    f"[SourceManager] {name} 采集完成，共 {count} 条帖子"
                )
            except Exception as e:
                logger.warning(
                    f"[SourceManager] {name} 批量采集失败: {e}，跳过该数据源"
                )
                all_results[name] = {}

        total_posts = sum(
            sum(len(posts) for posts in src.values())
            for src in all_results.values()
        )
        logger.info(
            f"[SourceManager] 全部采集完成，"
            f"{len(all_results)} 个数据源，共 {total_posts} 条帖子"
        )

        return all_results

    def get_active_weights(self) -> Dict[str, float]:
        """获取当前可用数据源的归一化权重

        仅包含已启用且通过健康检查的数据源，权重重新归一化使总和为1.0。

        Returns:
            {source_name: normalized_weight}
        """
        active_weights = {}

        for name in self.sources:
            # 数据源必须通过健康检查
            if not self._health_status.get(name, False):
                continue

            src_config = self.source_configs.get(name, {})
            weight = src_config.get('weight', 0.0)
            if weight > 0:
                active_weights[name] = weight

        # 归一化
        total = sum(active_weights.values())
        if total > 0:
            active_weights = {
                name: w / total for name, w in active_weights.items()
            }
        else:
            logger.warning(
                "[SourceManager] 没有可用的数据源，权重为空"
            )

        return active_weights

    def get_summary(self) -> str:
        """生成数据源状态摘要（人类可读）

        Returns:
            格式化的状态摘要字符串
        """
        lines = ["=== 社交媒体数据源状态 ==="]

        if not self.sources:
            lines.append("  (无已加载的数据源)")
            return "\n".join(lines)

        for name in sorted(self.sources.keys()):
            src_config = self.source_configs.get(name, {})
            weight = src_config.get('weight', 0.0)
            healthy = self._health_status.get(name)
            post_count = self._post_counts.get(name, 0)

            if healthy is None:
                health_str = "未检查"
            elif healthy:
                health_str = "正常"
            else:
                health_str = "异常"

            lines.append(
                f"  {name}: 权重={weight:.0%}, "
                f"状态={health_str}, "
                f"已采集={post_count}条"
            )

        # 汇总
        active = self.get_active_weights()
        total_posts = sum(self._post_counts.values())
        lines.append(f"--- 活跃数据源: {len(active)}/{len(self.sources)}, "
                      f"总采集: {total_posts}条 ---")

        if active:
            weight_strs = [f"{n}={w:.0%}" for n, w in sorted(active.items())]
            lines.append(f"--- 归一化权重: {', '.join(weight_strs)} ---")

        return "\n".join(lines)
