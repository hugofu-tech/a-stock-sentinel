#!/bin/bash
# 测试脚本 - 验证各模块功能

echo "🧪 A股情绪选股系统 - 模块测试"
echo "================================"

# 检查Python环境
echo ""
echo "1. 检查Python环境..."
python3 --version || { echo "❌ Python3 未安装"; exit 1; }
echo "✅ Python 检查通过"

# 检查依赖
echo ""
echo "2. 检查依赖包..."
python3 -c "import akshare" 2>/dev/null && echo "✅ akshare 已安装" || echo "⚠️ akshare 未安装 (运行: pip install akshare)"
python3 -c "import requests" 2>/dev/null && echo "✅ requests 已安装" || echo "⚠️ requests 未安装"
python3 -c "import pandas" 2>/dev/null && echo "✅ pandas 已安装" || echo "⚠️ pandas 未安装"

# 测试各模块
echo ""
echo "3. 测试模块导入..."

cd "$(dirname "$0")"

echo -n "  - data_fetcher.py: "
python3 -c "from data_fetcher import DataFetcher; print('✅ 正常')" 2>/dev/null || echo "❌ 导入失败"

echo -n "  - sentiment_analyzer.py: "
python3 -c "from sentiment_analyzer import SentimentAnalyzer; print('✅ 正常')" 2>/dev/null || echo "❌ 导入失败"

echo -n "  - stock_screener.py: "
python3 -c "from stock_screener import StockScreener; print('✅ 正常')" 2>/dev/null || echo "❌ 导入失败"

echo -n "  - holding_advisor.py: "
python3 -c "from holding_advisor import HoldingAdvisor; print('✅ 正常')" 2>/dev/null || echo "❌ 导入失败"

echo -n "  - feishu_pusher.py: "
python3 -c "from feishu_pusher import FeishuPusher; print('✅ 正常')" 2>/dev/null || echo "❌ 导入失败"

echo ""
echo "4. 运行本地测试（不发送飞书）..."
echo "--------------------------------"
python3 main.py --no-send

echo ""
echo "================================"
echo "✅ 测试完成"
