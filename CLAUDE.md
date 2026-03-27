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
- [x] config.py — 扩展配置（社交源/NLP/邮件/评分权重/交易策略）
- [x] 验证测试（全部通过）

### 2026-03-26 Phase 1: 东方财富股吧 + NLP + 回测
- [x] social/eastmoney_guba.py — 股吧爬虫（双策略：API+HTML降级）
- [x] nlp/snownlp_analyzer.py — SnowNLP批量分析器
- [x] nlp/sentiment_scorer.py — 多源情绪评分聚合+时间衰减
- [x] backtest/engine.py — 回测引擎（T+1、手续费、止损止盈）
- [x] backtest/metrics.py — 绩效指标（夏普、回撤、胜率等）
- [x] 集成测试通过
- [x] 股吧实际爬取测试（15只股票，300条帖子，HTML嵌入JSON方式）
- **发现**: SnowNLP对中文股评精度有限，LLM验证层(Phase 5)将弥补

### 2026-03-26 Phase 2-4: 其余三个社交媒体爬虫
- [x] social/xueqiu_crawler.py — 雪球评论爬虫（Cookie session+双API+大V加权）
- [x] social/weibo_stock.py — 微博股票爬虫（移动端API+四重噪声过滤）
- [x] social/shizifengyun.py — 市值风云文章爬虫（三级降级策略）
- [x] social/source_manager.py — 多源编排器（动态导入+健康检查+降级容错）
- **沙盒环境限制**: 雪球(阿里云WAF需JS)、微博(Sina Visitor需JS)、市值风云(代理封锁)
  - 东方财富正常工作
  - 其余三个代码已完成，待部署腾讯云后启用
### 2026-03-26 Phase 5-7: LLM验证 + 统一评分 + 通知调度
- [x] nlp/llm_analyzer.py — Kimi K2.5 LLM验证层（7维度分析，三级JSON解析）
- [x] sentiment_stock_scorer.py — 统一评分引擎（技术30%+资金20%+情绪40%+风控10%）
- [x] scheduler.py — 双流水线调度器（夜间采集+早间评分，CLI入口）
- [x] notification/email_sender.py — QQ邮箱通知（Markdown→HTML转换）
- [x] notification/feishu_sender.py — 飞书通知（Token缓存+Webhook降级）
- [x] requirements.txt 更新
- [x] 端到端集成测试通过（15股→300帖→NLP分析→评分→Top3推荐）
- [ ] Phase 8 全面回测

### 2026-03-26 修复记录
- [x] T+1语义修正：信号当天买入，买入当天不能卖出（非信号延迟执行）
- [x] SourceManager跳过健康检查未通过的数据源，避免无效重试

### 2026-03-26 腾讯云部署
- [x] 部署脚本 deploy_tencent.sh（一键部署+crontab定时任务）
- [x] Kimi K2.5 API 测试通过（endpoint: api.kimi.com/coding/v1）
- [x] 腾讯云部署成功（49.232.132.165，Ubuntu，北京时区）
- [x] 全流程测试：夜间管线成功（15股/300帖/0错误）
- [ ] 全流程测试：晨间管线结果待确认
- [ ] akshare全A股数据获取验证（当前用默认15只蓝筹测试）
- **注意**: 测试用的是大市值蓝筹股，正式运行时akshare筛选10-200亿小市值

### 2026-03-26 代码质量优化
- [x] scheduler.py: run_full_pipeline返回dict格式
- [x] eastmoney_guba.py: 优先HTML解析，减少无效API重试
- [x] config.py: python-dotenv自动加载.env + 日志绝对路径
- [x] deploy_tencent.sh: 移除硬编码密钥

### 2026-03-26 Phase 8 准备
- [x] backtest/data_collector.py — 历史数据收集器（akshare+缓存）
- [x] backtest/run_backtest.py — 回测运行脚本（启发式信号+随机基线对比）

### 整体进度
- Phase 0-7 代码开发完成，端到端流水线验证通过
- 东方财富股吧全链路正常（15股×20帖=300条/批次）
- 雪球/微博/市值风云 代码完成，待部署腾讯云后启用（沙盒JS限制）
- 腾讯云部署完成，定时任务已配置（22:00夜间/8:30晨间）
- akshare在国内IP（腾讯云）应正常工作，沙盒(美国IP)被屏蔽是预期行为
- 腾讯API备选方案已验证：4588只全A股，筛选后1132只（10-200亿小市值）
- 下一步：服务器同步最新代码 → 验证akshare/全A股筛选 → 全面回测调优

## 工作原则（老板要求）
1. **万无一失再上线**：不能让老板等不确定的结果。所有准备工作必须提前完成、验证通过，才告诉老板"可以上线了"
2. **减少老板工作量**：需要老板配合的操作打包成一条命令，绝不零散地反复麻烦
3. **多线程工作**：等待时做其他任务，不浪费时间
4. **定期汇报**：复杂任务每15分钟汇报进展
5. **主动执行**：能自己完成的事不问老板

## 关键决策记录
1. **为什么SnowNLP+LLM混合**: 10000条文本纯LLM太贵(>$30/天)，SnowNLP<2分钟处理完，LLM仅验证Top10(<$1/天)
2. **为什么情绪权重40%**: 项目核心是情绪选股，文献支持情绪因子显著超额收益(171% vs 73% benchmark)
3. **为什么SQLite**: 零配置、文件便携、WAL模式支持并发，适合单机部署
4. **开发顺序**: 东方财富→雪球→微博→市值风云，按数据量和API友好度排序

## 老板待提供信息
- [x] QQ邮箱SMTP授权码（已提供：fyf1028@qq.com）
- [x] Kimi K2.5 API Key（已提供，Coding Plan Allegretto）
- [x] 腾讯云服务器（已购买，49.232.132.165）
