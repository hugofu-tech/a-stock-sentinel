# A股情绪晨间预警 - GitHub Actions版

## 功能
每天早上9:15自动推送A股情绪分析报告到飞书

## 与之前版本的区别

| 特性 | 旧版本 (github-crawler) | 新版本 (a_stock_sentinel) |
|------|------------------------|--------------------------|
| 数据源 | B站/微博（需要Cookie，易被封） | akshare（纯Python库，稳定） |
| 反爬风险 | 高 | 低 |
| 维护成本 | 高（需更新Cookie） | 低（无需登录） |
| 数据类型 | 社交媒体情绪 | 市场实时数据 |
| 选股能力 | ❌ 无 | ✅ 全A股情绪选股TOP5 |

## 部署步骤

### 1. 创建GitHub仓库

```bash
# 在GitHub上创建新仓库，例如：a-stock-sentinel
cd /Users/hugo/.openclaw/workspace/a_stock_sentinel

# 初始化git仓库
git init
git add .
git commit -m "Initial commit"

# 关联远程仓库
git remote add origin https://github.com/您的用户名/a-stock-sentinel.git
git push -u origin main
```

### 2. 配置飞书Webhook

1. 在飞书群中添加「自定义机器人」
2. 复制Webhook地址（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx`）
3. 在GitHub仓库 Settings → Secrets → Actions 中添加：
   - Name: `FEISHU_WEBHOOK_URL`
   - Value: 您的Webhook地址

### 3. 手动测试

在GitHub仓库页面：
1. 点击 Actions 标签
2. 选择 "A股情绪晨间预警"
3. 点击 "Run workflow" 手动触发

### 4. 查看结果

- 成功：飞书收到情绪分析报告
- 失败：在Actions日志中查看错误信息

## 定时任务

- **时间**: 每天北京时间9:15 (UTC 1:15)
- **工作日**: 周一至周五
- **节假日**: 自动跳过（需要手动配置或代码判断）

## 报告内容

1. **市场概况** - 上证、深证、创业板指
2. **板块热度TOP5** - 涨幅最大的板块
3. **情绪选股TOP5** - 全A股情绪得分最高的5只股票
   - 股票名称、代码
   - 当前价格、涨幅
   - 情绪分数
   - 建议持有时间

## 技术栈

- Python 3.11
- akshare（A股数据）
- pandas（数据处理）
- requests（飞书推送）

## 调试

本地测试：
```bash
export FEISHU_WEBHOOK_URL="您的webhook地址"
python main_github.py
```

## 常见问题

### Q: 为什么选akshare而不是直接爬取？
A: akshare是专业的金融数据接口库，数据源稳定，无需处理反爬，维护成本低。

### Q: 选股算法的准确性如何？
A: 当前MVP版本使用简化算法（涨幅×换手率），后续可以根据回测结果优化。

### Q: 可以添加更多数据源吗？
A: 可以，只需要在代码中添加相应的数据获取函数即可。

---
**创建时间**: 2026-03-02
**版本**: v1.0.0 MVP
