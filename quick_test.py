#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股情绪选股系统 - 快速测试版
使用akshare稳定接口
"""

import sys
sys.path.insert(0, '/Users/hugo/.openclaw/workspace/a_stock_sentinel')

from datetime import datetime
import akshare as ak

def quick_test():
    """快速测试核心功能"""
    print("🚀 A股情绪选股系统 - 快速测试")
    print("=" * 50)
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 1. 获取市场概况
    print("📊 Step 1: 获取市场概况...")
    try:
        df_index = ak.stock_zh_index_spot_em()
        print(f"✅ 获取到 {len(df_index)} 个指数")
        
        # 显示主要指数
        for _, row in df_index.head(5).iterrows():
            name = row.get('名称', '')
            price = row.get('最新价', 0)
            change = row.get('涨跌幅', 0)
            print(f"   {name}: {price} ({change:+.2f}%)")
    except Exception as e:
        print(f"❌ 失败: {e}")
    
    # 2. 获取全A股数据
    print("\n📈 Step 2: 获取全A股数据...")
    try:
        df_stocks = ak.stock_zh_a_spot_em()
        print(f"✅ 获取到 {len(df_stocks)} 只股票")
        
        # 显示前5只
        print("\n   前5只股票:")
        for _, row in df_stocks.head(5).iterrows():
            name = row.get('名称', '')
            code = row.get('代码', '')
            price = row.get('最新价', 0)
            change = row.get('涨跌幅', 0)
            print(f"   {name}({code}): ¥{price} ({change:+.2f}%)")
    except Exception as e:
        print(f"❌ 失败: {e}")
        return
    
    # 3. 简单选股（涨幅前5）
    print("\n🎯 Step 3: 涨幅TOP5...")
    try:
        # 排除ST，按涨幅排序
        df_filtered = df_stocks[~df_stocks['名称'].str.contains('ST', na=False)]
        df_filtered = df_filtered[df_filtered['涨跌幅'] < 20]  # 排除新股
        df_top = df_filtered.nlargest(5, '涨跌幅')
        
        print("\n   🏆 今日涨幅TOP5:")
        for i, (_, row) in enumerate(df_top.iterrows(), 1):
            name = row.get('名称', '')
            code = row.get('代码', '')
            change = row.get('涨跌幅', 0)
            print(f"   {i}. {name}({code}): +{change:.2f}%")
    except Exception as e:
        print(f"❌ 失败: {e}")
    
    # 4. 板块热度
    print("\n🔥 Step 4: 板块热度...")
    try:
        df_sector = ak.stock_sector_change_em()
        print(f"✅ 获取到 {len(df_sector)} 个板块")
        
        print("\n   涨幅TOP5板块:")
        for i, (_, row) in enumerate(df_sector.head(5).iterrows(), 1):
            name = row.get('板块', '')
            change = row.get('涨跌幅', 0)
            leader = row.get('领涨股', '')
            print(f"   {i}. {name}: +{change:.2f}% (领涨: {leader})")
    except Exception as e:
        print(f"❌ 失败: {e}")
    
    print("\n" + "=" * 50)
    print("✅ 测试完成!")

if __name__ == "__main__":
    quick_test()
