# A股情绪选股系统 — 开发记录

## 项目概述
基于社交媒体（东方财富股吧、雪球、微博、市值风云）情绪分析的A股选股系统。
每日开盘前推荐2-3只买入/卖出股票，仅在9:30或10:00交易。

## 技术栈
- **NLP**: SnowNLP批量 + Kimi K2.5精选验证
- **数据存储**: SQLite
- **通知**: QQ邮箱 + 飞书
- **部署**: 腾讯云服务器（开发阶段用GitHub Actions）
- **数据源**: akshare + baostock + 四个社交媒体平台

## 评分模型
- 技术面 30% + 资金面 20% + 社交情绪 40% + 风险调整 10%
- 股票筛选: 流通市值10-200亿 + 10日均换手率3%-45% + 排除ST/涨停

## 开发进展

### 2026-03-26 Phase 0: 基础设施
- [x] 创建项目目录结构 (social/, nlp/, storage/, backtest/, notification/)
- [x] storage/models.py — 数据模型 (SocialPost, SentimentResult, StockSentimentAggregate, StockCandidate, DailyRecommendation)
- [x] storage/sqlite_store.py — SQLite存储层 (帖子、情绪分数、推荐记录、回测结果)
- [x] social/base_source.py — 爬虫抽象基类 (rate limit, 重试, UA轮换)
- [ ] config.py — 扩展配置
- [x] 验证测试（全部通过）

### 2026-03-26 Phase 1: 东方财富股吧 + NLP + 回测
- [x] social/eastmoney_guba.py — 股吧爬虫（双策略：API+HTML降级）
- [x] nlp/snownlp_analyzer.py — SnowNLP批量分析器
- [x] nlp/sentiment_scorer.py — 多源情绪评分聚合+时间衰减
- [x] backtest/engine.py — 回测引擎（T+1、手续费、止损止盈）
- [x] backtest/metrics.py — 绩效指标（夏普、回撤、胜率等）
- [x] 集成测试通过
- [ ] 股吧实际爬取测试
- **发现**: SnowNLP对中文股评精度有限，LLM验证层(Phase 5)将弥补

## 关键决策记录
1. **为什么SnowNLP+LLM混合**: 10000条文本纯LLM太贵(>$30/天)，SnowNLP<2分钟处理完，LLM仅验证Top10(<$1/天)
2. **为什么情绪权重40%**: 项目核心是情绪选股，文献支持情绪因子显著超额收益(171% vs 73% benchmark)
3. **为什么SQLite**: 零配置、文件便携、WAL模式支持并发，适合单机部署
4. **开发顺序**: 东方财富→雪球→微博→市值风云，按数据量和API友好度排序

## 老板待提供信息
- [ ] QQ邮箱SMTP授权码（Phase 7时需要）
- [ ] Kimi K2.5 API Key（Phase 5时需要）
- [ ] 腾讯云服务器（部署阶段时需要）
