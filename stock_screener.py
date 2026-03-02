#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个股筛选器 - 全A股情绪量化排序
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import akshare as ak
except ImportError:
    ak = None


class StockScreener:
    """个股情绪筛选器"""
    
    # 情绪评分权重配置
    WEIGHTS = {
        'sentiment_heat': 0.30,      # 舆情热度
        'fund_flow': 0.25,            # 资金流向
        'tech_emotion': 0.25,         # 技术情绪
        'market_resonance': 0.20      # 市场共振
    }
    
    # 筛选条件
    FILTER_CONFIG = {
        'min_market_cap': 10,         # 最小流通市值(亿)
        'min_amount': 0.5,            # 最小成交额(亿)
        'exclude_st': True,           # 排除ST股票
        'max_price': 200,             # 最大股价(避免太贵)
        'min_price': 2                # 最小股价(避免仙股)
    }
    
    def __init__(self):
        self.stock_data = None
        self.hot_sectors = set()
    
    def fetch_all_stocks(self) -> pd.DataFrame:
        """获取全A股实时数据"""
        if ak is None:
            print("❌ akshare 未安装")
            return pd.DataFrame()
        
        print("📊 正在获取全A股数据...")
        
        try:
            # 获取沪深A股实时行情
            df = ak.stock_zh_a_spot_em()
            print(f"✅ 获取到 {len(df)} 只股票数据")
            return df
            
        except Exception as e:
            print(f"❌ 获取股票数据失败: {e}")
            return pd.DataFrame()
    
    def filter_stocks(self, df: pd.DataFrame) -> pd.DataFrame:
        """过滤股票"""
        config = self.FILTER_CONFIG
        original_count = len(df)
        
        # 排除ST股票
        if config['exclude_st']:
            df = df[~df['名称'].str.contains('ST|st|退', na=False)]
        
        # 流通市值过滤 (单位：亿)
        df = df[df['流通市值'].astype(float) / 100000000 >= config['min_market_cap']]
        
        # 成交额过滤 (单位：亿)
        df = df[df['成交额'].astype(float) / 100000000 >= config['min_amount']]
        
        # 股价过滤
        df = df[(df['最新价'].astype(float) >= config['min_price']) & 
                (df['最新价'].astype(float) <= config['max_price'])]
        
        filtered_count = len(df)
        print(f"📊 过滤后: {filtered_count}/{original_count} 只")
        
        return df
    
    def calculate_sentiment_score(self, df: pd.DataFrame, hot_sectors: List[Dict] = None) -> pd.DataFrame:
        """计算情绪得分"""
        print("🧮 正在计算情绪得分...")
        
        # 保存热门板块信息
        if hot_sectors:
            self.hot_sectors = {s['name'] for s in hot_sectors}
        
        # 计算各维度得分
        df['score_heat'] = self._calc_heat_score(df)           # 舆情热度
        df['score_fund'] = self._calc_fund_score(df)           # 资金流向
        df['score_tech'] = self._calc_tech_score(df)           # 技术情绪
        df['score_resonance'] = self._calc_resonance_score(df) # 市场共振
        
        # 加权总分 (0-100)
        weights = self.WEIGHTS
        df['sentiment_score'] = (
            df['score_heat'] * weights['sentiment_heat'] +
            df['score_fund'] * weights['fund_flow'] +
            df['score_tech'] * weights['tech_emotion'] +
            df['score_resonance'] * weights['market_resonance']
        ) * 100
        
        df['sentiment_score'] = df['sentiment_score'].round(1)
        
        return df
    
    def _calc_heat_score(self, df: pd.DataFrame) -> pd.Series:
        """
        舆情热度评分 (0-1)
        基于：涨跌幅、换手率、量比
        """
        # 涨跌幅因子 (-10% ~ +10% 映射到 0-0.5)
        change = df['涨跌幅'].astype(float)
        change_score = (change + 10) / 40  # -10->0, +10->0.5
        change_score = change_score.clip(0, 0.5)
        
        # 换手率因子 (0-20% 映射到 0-0.3)
        turnover = df['换手率'].astype(float)
        turnover_score = turnover / 20 * 0.3
        turnover_score = turnover_score.clip(0, 0.3)
        
        # 量比因子 (0-5 映射到 0-0.2)
        volume_ratio = df['量比'].astype(float)
        ratio_score = volume_ratio / 5 * 0.2
        ratio_score = ratio_score.clip(0, 0.2)
        
        return change_score + turnover_score + ratio_score
    
    def _calc_fund_score(self, df: pd.DataFrame) -> pd.Series:
        """
        资金流向评分 (0-1)
        基于：主力净流入占比
        """
        # 使用成交额和涨跌估算资金流向
        amount = df['成交额'].astype(float)
        change = df['涨跌幅'].astype(float)
        
        # 上涨+放量 = 资金流入
        # 简化计算：涨幅为正，得分基础0.5，加上涨幅/20
        fund_score = 0.3 + change / 20
        
        # 成交额因子 (大盘更受关注)
        amount_factor = (amount / amount.max()).clip(0, 0.3)
        
        return (fund_score + amount_factor).clip(0, 1)
    
    def _calc_tech_score(self, df: pd.DataFrame) -> pd.Series:
        """
        技术情绪评分 (0-1)
        基于：涨停强度、换手、量比综合
        """
        # 涨停判断 (涨幅>9.5%)
        change = df['涨跌幅'].astype(float)
        limit_up = (change > 9.5).astype(float) * 0.4
        
        # 强势上涨 (5-9.5%)
        strong_up = ((change > 5) & (change <= 9.5)).astype(float) * 0.25
        
        # 换手活跃度
        turnover = df['换手率'].astype(float)
        turnover_score = (turnover / 15).clip(0, 0.2)
        
        # 量比活跃度
        volume_ratio = df['量比'].astype(float)
        ratio_score = (volume_ratio / 3).clip(0, 0.15)
        
        return (limit_up + strong_up + turnover_score + ratio_score).clip(0, 1)
    
    def _calc_resonance_score(self, df: pd.DataFrame) -> pd.Series:
        """
        市场共振评分 (0-1)
        基于：所属板块热度、市场整体情绪
        """
        # 简化：根据涨跌幅和成交额判断与市场共振程度
        change = df['涨跌幅'].astype(float)
        amount = df['成交额'].astype(float)
        
        # 涨幅适中且成交活跃 = 与市场共振
        # 大涨大跌 = 个股行情
        resonance = 0.5 - abs(change - 3) / 10  # 涨幅3%左右得分最高
        resonance = resonance.clip(0, 0.5)
        
        # 成交活跃度加分
        amount_score = (amount / amount.quantile(0.9)).clip(0, 0.5)
        
        return (resonance + amount_score).clip(0, 1)
    
    def get_top_picks(self, df: pd.DataFrame, n: int = 5) -> List[Dict]:
        """获取TOP N推荐股票"""
        if df.empty:
            return []
        
        # 按情绪得分排序
        df_sorted = df.sort_values('sentiment_score', ascending=False)
        
        # 选择需要的列
        columns = ['代码', '名称', '最新价', '涨跌幅', '换手率', '成交额', 
                   'sentiment_score', 'score_heat', 'score_fund', 'score_tech', 'score_resonance']
        
        available_cols = [c for c in columns if c in df_sorted.columns]
        df_top = df_sorted[available_cols].head(n)
        
        # 转换为字典列表
        result = []
        for _, row in df_top.iterrows():
            stock = {
                'code': str(row.get('代码', '')),
                'name': str(row.get('名称', '')),
                'price': float(row.get('最新价', 0)),
                'change_percent': float(row.get('涨跌幅', 0)),
                'turnover': float(row.get('换手率', 0)),
                'amount': float(row.get('成交额', 0)) / 100000000,  # 转为亿
                'sentiment_score': float(row.get('sentiment_score', 0)),
                'heat_score': float(row.get('score_heat', 0)) * 100,
                'fund_score': float(row.get('score_fund', 0)) * 100,
                'tech_score': float(row.get('score_tech', 0)) * 100,
                'resonance_score': float(row.get('score_resonance', 0)) * 100
            }
            result.append(stock)
        
        return result
    
    def screen(self, hot_sectors: List[Dict] = None) -> List[Dict]:
        """
        执行完整筛选流程
        
        Returns:
            TOP 5 推荐股票列表
        """
        print("\n🔍 开始个股情绪筛选...")
        
        # 1. 获取数据
        df = self.fetch_all_stocks()
        if df.empty:
            return []
        
        # 2. 过滤
        df = self.filter_stocks(df)
        
        # 3. 计算情绪得分
        df = self.calculate_sentiment_score(df, hot_sectors)
        
        # 4. 获取TOP5
        top_stocks = self.get_top_picks(df, n=5)
        
        print(f"✅ 筛选完成，选出TOP{len(top_stocks)}股票")
        
        return top_stocks


# 测试代码
if __name__ == '__main__':
    screener = StockScreener()
    top_stocks = screener.screen()
    
    print("\n📈 TOP 5 推荐股票：")
    for i, stock in enumerate(top_stocks, 1):
        print(f"{i}. {stock['name']}({stock['code']}) - 情绪分: {stock['sentiment_score']}")
