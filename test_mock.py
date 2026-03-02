#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股情绪晨间预警 - 测试版（带模拟数据）
用于演示报告格式
"""

from datetime import datetime


def mock_test():
    """使用模拟数据测试报告格式"""
    print("🚀 A股情绪晨间预警系统 - 模拟测试")
    print("=" * 50)
    print(f"⏰ 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 模拟市场数据
    market = {
        'sh': {'name': '上证指数', 'value': 3320.50, 'change': 0.85},
        'sz': {'name': '深证成指', 'value': 11850.30, 'change': 1.12},
        'cy': {'name': '创业板指', 'value': 2450.80, 'change': 1.35}
    }
    
    # 模拟板块数据
    sectors = [
        {'name': '人工智能', 'change': 3.45},
        {'name': '芯片半导体', 'change': 2.89},
        {'name': '新能源', 'change': 2.56},
        {'name': '医药生物', 'change': 1.98},
        {'name': '消费电子', 'change': 1.76}
    ]
    
    # 模拟选股数据
    stocks = [
        {'name': '赛力斯', 'code': '601127', 'price': 95.80, 'change': 8.5, 'turnover': 12.5, 'amount': 15.8, 'score': 106.25},
        {'name': '工业富联', 'code': '601138', 'price': 24.60, 'change': 6.8, 'turnover': 8.2, 'amount': 22.5, 'score': 55.76},
        {'name': '中际旭创', 'code': '300308', 'price': 158.30, 'change': 5.9, 'turnover': 6.8, 'amount': 18.2, 'score': 40.12},
        {'name': '中科曙光', 'code': '603019', 'price': 52.40, 'change': 4.2, 'turnover': 9.5, 'amount': 12.8, 'score': 39.90},
        {'name': '浪潮信息', 'code': '000977', 'price': 38.90, 'change': 3.8, 'turnover': 7.2, 'amount': 8.5, 'score': 27.36}
    ]
    
    # 生成报告
    now = datetime.now().strftime('%m月%d日 %H:%M')
    
    market_text = ""
    for key in ['sh', 'sz', 'cy']:
        m = market[key]
        emoji = "📈" if m['change'] >= 0 else "📉"
        market_text += f"{emoji} **{m['name']}**: {m['value']:.2f} ({m['change']:+.2f}%)\n"
    
    sector_text = ""
    for i, s in enumerate(sectors, 1):
        sector_text += f"{i}. **{s['name']}**: {s['change']:+.2f}%\n"
    
    stock_text = ""
    for i, s in enumerate(stocks, 1):
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
        if s['change'] > 5:
            hold = "1-2天（超短线）"
        elif s['change'] > 2:
            hold = "2-3天（短线）"
        else:
            hold = "3-5天（波段）"
        
        stock_text += f"{emoji} **{s['name']}**({s['code']})\n"
        stock_text += f"   价格: ¥{s['price']:.2f} | 涨幅: {s['change']:+.2f}% | 换手: {s['turnover']:.1f}%\n"
        stock_text += f"   成交额: {s['amount']:.1f}亿 | 情绪分: {s['score']:.1f}\n"
        stock_text += f"   💡 建议持有: {hold}\n\n"
    
    report = f"""📊 **A股情绪晨间预警** | {now}

---

### 📈 市场概况

{market_text}
---

### 🔥 板块热度TOP5

{sector_text}
---

### 🎯 情绪选股TOP5

{stock_text}
---

⚠️ **免责声明**：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。

🤖 *本报告由AI自动生成*
"""
    
    print(report)
    return report


if __name__ == "__main__":
    report = mock_test()
