# A股情绪晨间预警 - GitHub Actions版

## 功能
每天早上9:15自动推送A股情绪分析报告到飞书

## 部署步骤

### 1. 创建GitHub仓库

```bash
cd /Users/hugo/.openclaw/workspace/a_stock_sentinel

# 初始化git仓库
git init
git add .
git commit -m "A股情绪预警系统 v1.0"

# 在GitHub创建仓库 a-stock-sentinel
git remote add origin https://github.com/您的用户名/a-stock-sentinel.git
git push -u origin main
```

### 2. 配置GitHub Secrets

在GitHub仓库 Settings → Secrets → Actions 中添加：

| Secret Name | Value | 说明 |
|-------------|-------|------|
| `FEISHU_APP_ID` | cli_a9f70dfaa379dbd7 | 飞书应用ID |
| `FEISHU_APP_SECRET` | j5MoWSysARI0tQLLfeywWfKRXEunzv7Y | 飞书应用Secret |
| `FEISHU_TARGET` | user:ou_0ad234b6ebfca4f424bd582393734d0f | 发送目标（老板的用户ID）|

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
- **节假日**: 自动运行（需要代码判断是否为交易日）

## 报告内容

1. **市场概况** - 上证、深证、创业板指
2. **板块热度TOP5** - 涨幅最大的板块
3. **情绪选股TOP5** - 全A股情绪得分最高的5只股票
   - 股票名称、代码
   - 当前价格、涨幅、换手率
   - 情绪分数
   - 建议持有时间

## 技术栈

- Python 3.11
- akshare（A股数据）
- pandas（数据处理）
- requests（飞书API）

## 本地测试

```bash
export FEISHU_APP_ID="cli_a9f70dfaa379dbd7"
export FEISHU_APP_SECRET="j5MoWSysARI0tQLLfeywWfKRXEunzv7Y"
export FEISHU_TARGET="user:ou_0ad234b6ebfca4f424bd582393734d0f"

pip install akshare pandas requests
python main.py
```

## 常见问题

### Q: 为什么用GitHub Actions而不是本地运行？
A: GitHub Actions服务器网络无限制，可以稳定获取akshare数据，本地网络可能受限。

### Q: 选股算法的准确性如何？
A: 当前版本使用简化算法（涨幅×换手率），后续可以根据回测结果优化。

### Q: 如何修改发送时间？
A: 修改 `.github/workflows/daily-sentinel.yml` 中的cron表达式：
- `'15 1 * * 1-5'` = 北京时间9:15（周一至周五）
- `'0 23 * * 0-4'` = 北京时间7:00（周一至周五）

### Q: 飞书没收到消息怎么办？
A: 检查：
1. GitHub Actions运行状态（绿色✓表示成功）
2. Secrets配置是否正确
3. 查看Actions日志中的错误信息

---
**创建时间**: 2026-03-02
**版本**: v1.0.0
**作者**: 小贾
