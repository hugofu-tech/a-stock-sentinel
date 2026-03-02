#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取模块 - 稳定版 (主要使用akshare)
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

# akshare 导入
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("⚠️ akshare 未安装，请运行: pip install akshare")


class DataFetcher:
    """数据获取器 - 稳定版"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        self.cache = {}
    
    def get_all_data(self) -> Dict:
        """获取所有市场数据（稳定版）"""
        data = {
            'market_overview': self.get_market_overview(),
            'sector_heat': self.get_sector_heat(),
            'limit_up_down': self.get_limit_up_down(),
            'north_bound': self.get_north_bound_flow(),
            'hot_concepts': self.get_hot_concepts(),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        return data
    
    def get_market_overview(self) -> Dict:
        """获取市场概况 - 使用akshare"""
        if not AKSHARE_AVAILABLE:
            return {}
        
        try:
            # 获取主要指数
            df = ak.stock_zh_index_spot_em()
            
            indices = {}
            for _, row in df.iterrows():
                name = row.get('名称', '')
                if '上证指数' in name:
                    indices['sh'] = {
                        'name': '上证指数',
                        'value': float(row.get('最新价', 0)),
                        'change': float(row.get('涨跌幅', 0)),
                        'change_amount': float(row.get('涨跌额', 0))
                    }
                elif '深证成指' in name:
                    indices['sz'] = {
                        'name': '深证成指', 
                        'value': float(row.get('最新价', 0)),
                        'change': float(row.get('涨跌幅', 0)),
                        'change_amount': float(row.get('涨跌额', 0))
                    }
                elif '创业板指' in name:
                    indices['cy'] = {
                        'name': '创业板指',
                        'value': float(row.get('最新价', 0)),
                        'change': float(row.get('涨跌幅', 0)),
                        'change_amount': float(row.get('涨跌额', 0))
                    }
            
            return indices
        except Exception as e:
            print(f"获取市场概况失败: {e}")
            return {}
    
    def get_sector_heat(self) -> List[Dict]:
        """获取板块热度 - 使用akshare行业板块"""
        if not AKSHARE_AVAILABLE:
            return []
        
        try:
            # 获取行业板块涨幅排行
            df = ak.stock_sector_change_em()
            
            sectors = []
            for i, row in df.head(10).iterrows():
                sectors.append({
                    'name': row.get('板块', ''),
                    'change': float(row.get('涨跌幅', 0)),
                    'leader': row.get('领涨股', '')
                })
            
            return sectors
        except Exception as e:
            print(f"获取板块热度失败: {e}")
            return []
    
    def get_limit_up_down(self) -> Dict:
        """获取涨跌停统计 - 使用akshare"""
        if not AKSHARE_AVAILABLE:
            return {'limit_up': 0, 'limit_down': 0}
        
        try:
            # 获取涨停池
            up_df = ak.stock_zt_pool_em(date=datetime.now().strftime('%Y%m%d'))
            limit_up = len(up_df) if up_df is not None else 0
            
            # 获取跌停池
            down_df = ak.stock_zt_pool_dtgc_em(date=datetime.now().strftime('%Y%m%d'))
            limit_down = len(down_df) if down_df is not None else 0
            
            return {
                'limit_up': limit_up,
                'limit_down': limit_down
            }
        except Exception as e:
            print(f"获取涨跌停数据失败: {e}")
            return {'limit_up': 0, 'limit_down': 0}
    
    def get_north_bound_flow(self) -> Dict:
        """获取北向资金流向 - 使用akshare"""
        if not AKSHARE_AVAILABLE:
            return {}
        
        try:
            # 获取北向资金历史数据，取最新一天
            df = ak.stock_hsgt_hist_em(symbol="沪股通")
            if df is not None and len(df) > 0:
                latest = df.iloc[0]
                return {
                    'sh': float(latest.get('当日资金流入', 0)),
                    'date': latest.get('日期', '')
                }
            
            # 再获取深股通
            df_sz = ak.stock_hsgt_hist_em(symbol="深股通")
            if df_sz is not None and len(df_sz) > 0:
                latest = df_sz.iloc[0]
                return {
                    'sz': float(latest.get('当日资金流入', 0)),
                    'date': latest.get('日期', '')
                }
            
            return {}
        except Exception as e:
            print(f"获取北向资金失败: {e}")
            return {}
    
    def get_hot_concepts(self) -> List[Dict]:
        """获取热门概念 - 使用akshare概念板块"""
        if not AKSHARE_AVAILABLE:
            return []
        
        try:
            # 获取概念板块涨幅排行
            df = ak.stock_board_concept_name_em()
            
            concepts = []
            for i, row in df.head(10).iterrows():
                concepts.append({
                    'name': row.get('板块名称', ''),
                    'change': float(row.get('涨跌幅', 0)),
                    'volume': float(row.get('总市值', 0)) if '总市值' in row else 0
                })
            
            return concepts
        except Exception as e:
            print(f"获取热门概念失败: {e}")
            return []


# 测试代码
if __name__ == "__main__":
    fetcher = DataFetcher()
    data = fetcher.get_all_data()
    print(json.dumps(data, ensure_ascii=False, indent=2))
