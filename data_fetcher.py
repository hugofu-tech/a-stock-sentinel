#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取模块 - 获取A股相关数据
支持：雪球、东方财富、微博等数据源
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

# akshare 导入
try:
    import akshare as ak
except ImportError:
    ak = None


class DataFetcher:
    """数据获取器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        self.cache = {}
        self.cache_time = 60  # 缓存60秒
    
    # ==================== 雪球数据 ====================
    
    def get_xueqiu_hot_stocks(self, limit: int = 20) -> List[Dict]:
        """
        获取雪球热门股票
        """
        url = f"https://stock.xueqiu.com/v5/stock/hot_stock/list.json?size={limit}&_type=10&_={int(time.time()*1000)}"
        
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            stocks = []
            for item in data.get('data', {}).get('items', []):
                stock = {
                    'name': item.get('name', ''),
                    'code': item.get('symbol', ''),
                    'price': item.get('current', 0),
                    'change_percent': item.get('percent', 0),
                    'volume': item.get('volume', 0),
                    'market_cap': item.get('market_capital', 0)
                }
                stocks.append(stock)
            
            return stocks
        except Exception as e:
            print(f"获取雪球热门股票失败: {e}")
            return []
    
    def get_xueqiu_limit_up_down(self) -> Dict:
        """
        获取涨跌停数据
        """
        cache_key = 'limit_up_down'
        if cache_key in self.cache:
            cache_data, cache_ts = self.cache[cache_key]
            if time.time() - cache_ts < self.cache_time:
                return cache_data
        
        url = f"https://stock.xueqiu.com/v5/stock/capital/market.json?_={int(time.time()*1000)}"
        
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            result = {
                'limit_up_count': 0,
                'limit_down_count': 0,
                'up_5_percent': 0,
                'down_5_percent': 0
            }
            
            market_data = data.get('data', {})
            result['limit_up_count'] = market_data.get('limit_up_count', 0)
            result['limit_down_count'] = market_data.get('limit_down_count', 0)
            
            self.cache[cache_key] = (result, time.time())
            return result
            
        except Exception as e:
            print(f"获取涨跌停数据失败: {e}")
            return {'limit_up_count': 0, 'limit_down_count': 0, 'up_5_percent': 0, 'down_5_percent': 0}
    
    # ==================== 东方财富数据 ====================
    
    def get_eastmoney_fund_flow(self) -> Dict:
        """
        获取东方财富资金流向数据
        """
        cache_key = 'fund_flow'
        if cache_key in self.cache:
            cache_data, cache_ts = self.cache[cache_key]
            if time.time() - cache_ts < self.cache_time:
                return cache_data
        
        # 使用 akshare 获取资金流向
        if ak is None:
            return {'main_inflow': 0, 'retail_inflow': 0, 'north_inflow': 0}
        
        try:
            # 北向资金流向
            north_df = ak.stock_hsgt_hist_em(symbol="沪股通")
            if not north_df.empty:
                latest = north_df.iloc[-1]
                north_inflow = float(latest.get('当日资金流入', 0))
            else:
                north_inflow = 0
            
            result = {
                'main_inflow': 0,  # 主力净流入（需要额外接口）
                'retail_inflow': 0,  # 散户净流入
                'north_inflow': north_inflow,  # 北向净流入
                'update_time': datetime.now().strftime('%H:%M')
            }
            
            self.cache[cache_key] = (result, time.time())
            return result
            
        except Exception as e:
            print(f"获取资金流向失败: {e}")
            return {'main_inflow': 0, 'retail_inflow': 0, 'north_inflow': 0}
    
    def get_eastmoney_sector_hot(self, limit: int = 10) -> List[Dict]:
        """
        获取东方财富热门板块
        """
        if ak is None:
            return []
        
        try:
            # 获取板块涨幅排行
            df = ak.stock_board_industry_name_em()
            
            sectors = []
            for _, row in df.head(limit).iterrows():
                sector = {
                    'name': row.get('板块名称', ''),
                    'change_percent': float(row.get('涨跌幅', 0)),
                    'volume': row.get('总成交量', 0),
                    'amount': row.get('总金额', 0)
                }
                sectors.append(sector)
            
            return sectors
            
        except Exception as e:
            print(f"获取热门板块失败: {e}")
            return []
    
    def get_eastmoney_market_overview(self) -> Dict:
        """
        获取市场概况数据（上证指数、深证成指、创业板指）
        """
        cache_key = 'market_overview'
        if cache_key in self.cache:
            cache_data, cache_ts = self.cache[cache_key]
            if time.time() - cache_ts < self.cache_time:
                return cache_data
        
        if ak is None:
            return {}
        
        try:
            # 获取指数数据
            indices = {
                'sh': {'name': '上证指数', 'code': '000001'},
                'sz': {'name': '深证成指', 'code': '399001'},
                'cy': {'name': '创业板指', 'code': '399006'}
            }
            
            result = {}
            
            # 获取实时行情
            df = ak.stock_zh_index_spot_em()
            
            for idx_code, idx_info in indices.items():
                code = idx_info['code']
                row = df[df['代码'] == code]
                if not row.empty:
                    result[idx_code] = {
                        'name': idx_info['name'],
                        'price': float(row.iloc[0].get('最新价', 0)),
                        'change': float(row.iloc[0].get('涨跌额', 0)),
                        'change_percent': float(row.iloc[0].get('涨跌幅', 0)),
                        'volume': row.iloc[0].get('成交量', 0),
                        'amount': row.iloc[0].get('成交额', 0)
                    }
            
            self.cache[cache_key] = (result, time.time())
            return result
            
        except Exception as e:
            print(f"获取市场概况失败: {e}")
            return {}
    
    def get_eastmoney_up_down_stats(self) -> Dict:
        """
        获取涨跌家数统计
        """
        if ak is None:
            return {'up': 0, 'down': 0, 'flat': 0}
        
        try:
            # 获取沪深A股涨跌统计
            df = ak.stock_zt_pool_em(date=datetime.now().strftime('%Y%m%d'))
            
            # 这里简化处理，实际可以更精确
            return {
                'up': len(df) if not df.empty else 0,
                'down': 0,
                'flat': 0
            }
            
        except Exception as e:
            print(f"获取涨跌统计失败: {e}")
            return {'up': 0, 'down': 0, 'flat': 0}
    
    # ==================== 综合数据接口 ====================
    
    def get_all_data(self) -> Dict:
        """
        获取所有数据（综合接口）
        """
        print("📊 正在获取数据...")
        
        data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'market_overview': self.get_eastmoney_market_overview(),
            'hot_stocks': self.get_xueqiu_hot_stocks(limit=10),
            'fund_flow': self.get_eastmoney_fund_flow(),
            'hot_sectors': self.get_eastmoney_sector_hot(limit=8),
            'limit_stats': self.get_xueqiu_limit_up_down()
        }
        
        print("✅ 数据获取完成")
        return data


# 测试代码
if __name__ == '__main__':
    fetcher = DataFetcher()
    data = fetcher.get_all_data()
    print(json.dumps(data, ensure_ascii=False, indent=2))