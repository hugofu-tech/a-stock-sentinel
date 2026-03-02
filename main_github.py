#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股情绪晨间预警 - GitHub Actions版
简化版，使用akshare稳定接口
"""

import os
import json
import requests
from datetime import datetime
import akshare as ak


def get_market_overview():
    """获取市场概况"""
    try:
        df = ak.stock_zh_index_spot_em()
        indices = {}
        for _, row in df.iterrows():
            name = row.get('名称', '')
            if '上证' in name and '指数' in name:
                indices['sh'] = {
                    'name': '上证指数',
                    'value': float(row.get('最新价', 0)),
                    'change': float(row.get('涨跌幅', 0))
                }
            elif '深证' in name:
                indices['sz'] = {
                    'name': '深证成指',
                    'value': float(row.get('最新价', 0)),
                    'change': float(row.get('涨跌幅', 0))
                }
            elif '创业板' in name:
                indices['cy'] = {
                    'name': '创业板指',
                    'value': float(row.get('最新价', 0)),
                    'change': float(row.get('涨跌幅', 0))
                }
        return indices
    except Exception as e:
        print(f"获取市场概况失败: {e}")
        return {}


def get_stock_screener():
    """全A股筛选，返回情绪TOP5"""
    try:
        df = ak.stock_zh_a_spot_em()
        
        # 筛选条件
        df = df[~df['名称'].str.contains('ST', na=False)]  # 排除ST
        df = df[df['最新价'] < 100]  # 股价低于100
        df = df[df['涨跌幅'] < 15]  # 排除新股暴涨
        df = df[df['成交额'] > 50000000]  # 成交额大于5000万
        
        # 简单情绪分 = 涨幅 * 换手率
        df['情绪分'] = df['涨跌幅'] * df['换手率']
        
        # 排序取前5
        top5 = df.nlargest(5, '情绪分')
        
        results = []
        for _, row in top5.iterrows():
            results.append({
                'name': row['名称'],
                'code': row['代码'],
                'price': row['最新价'],
                'change': row['涨跌幅'],
                'turnover': row['换手率'],
                'amount': row['成交额'] / 100000000,  # 转成亿
                'score': round(row['情绪分'], 2)
            })
        
        return results
    except Exception as e:
        print(f"选股失败: {e}")
        return []


def get_sector_heat():
    """获取板块热度"""
    try:
        df = ak.stock_sector_change_em()
        sectors = []
        for _, row in df.head(5).iterrows():
            sectors.append({
                'name': row['板块'],
                'change': row['涨跌幅']
            })
        return sectors
    except Exception as e:
        print(f"获取板块热度失败: {e}")
        return []


def generate_report(market, stocks, sectors):
    """生成飞书报告"""
    now = datetime.now().strftime('%m月%d日 %H:%M')
    
    # 市场概况
    market_text = ""
    for key in ['sh', 'sz', 'cy']:
        if key in market:
            m = market[key]
            emoji = "📈" if m['change'] >= 0 else "📉"
            market_text += f"{emoji} **{m['name']}**: {m['value']:.2f} ({m['change']:+.2f}%)\n"
    
    # 板块热度
    sector_text = ""
    for i, s in enumerate(sectors, 1):
        sector_text += f"{i}. **{s['name']}**: {s['change']:+.2f}%\n"
    
    # 选股TOP5
    stock_text = ""
    for i, s in enumerate(stocks, 1):
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
        # 持有时间建议
        if s['change'] > 5:
            hold = "1-2天（超短线）"
        elif s['change'] > 2:
            hold = "2-3天（短线）"
        else:
            hold = "3-5天（波段）"
        
        stock_text += f"{emoji} **{s['name']}**({s['code']})\n"
        stock_text += f"   价格: ¥{s['price']:.2f} | 涨幅: {s['change']:+.2f}% | 换手: {s['turnover']:.1f}%\n"
        stock_text += f"   情绪分: {s['score']} | 建议持有: {hold}\n\n"
    
    report = f"""# 📊 A股情绪晨间预警 | {now}

---

## 📈 市场概况

{market_text}

---

## 🔥 板块热度TOP5

{sector_text}

---

## 🎯 情绪选股TOP5

{stock_text}

---

*⚠️ 免责声明：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。*
"""
    return report


def save_report(content):
    """保存报告到文件"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'report_{timestamp}.md'
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ 报告已保存到: {filename}")
    return filename


def main():
    print("🚀 A股情绪晨间预警系统")
    print("=" * 50)
    print(f"⏰ 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 获取数据
    print("📊 正在获取市场数据...")
    market = get_market_overview()
    print(f"✅ 获取到 {len(market)} 个指数")
    
    print("\n🔍 正在全市场选股...")
    stocks = get_stock_screener()
    print(f"✅ 选出 {len(stocks)} 只股票")
    
    print("\n🔥 正在获取板块热度...")
    sectors = get_sector_heat()
    print(f"✅ 获取到 {len(sectors)} 个板块")
    
    # 生成报告
    print("\n📝 正在生成报告...")
    report = generate_report(market, stocks, sectors)
    
    # 保存报告
    print("\n💾 正在保存报告...")
    save_report(report)
    
    print("\n✅ 完成! 报告内容如下:\n")
    print("=" * 50)
    print(report)
    print("=" * 50)
    
    return report


if __name__ == "__main__":
    main()
