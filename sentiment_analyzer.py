#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪分析模块 - 计算市场情绪指数和分析
"""

import json
from typing import Dict, List, Tuple
from datetime import datetime


class SentimentAnalyzer:
    """市场情绪分析器"""
    
    # 情绪指数阈值
    SENTIMENT_LEVELS = {
        'extreme_fear': (0, 20, '极度恐慌', '🔴'),
        'fear': (20, 40, '恐慌', '🟠'),
        'neutral': (40, 60, '中性', '🟡'),
        'greed': (60, 80, '贪婪', '🟢'),
        'extreme_greed': (80, 100, '极度贪婪', '🔵')
    }
    
    # 操作建议配置
    ADVICE_CONFIG = {
        'extreme_fear': {
            'action': '分批建仓',
            'description': '市场情绪极度悲观，可能是抄底机会，建议分批建仓优质标的',
            'risk_level': '低',
            'position_suggest': '30-50%'
        },
        'fear': {
            'action': '谨慎乐观',
            'description': '市场情绪偏悲观，可逢低布局，控制仓位',
            'risk_level': '中低',
            'position_suggest': '50-60%'
        },
        'neutral': {
            'action': '观望为主',
            'description': '市场情绪中性，保持现有仓位，等待明确信号',
            'risk_level': '中',
            'position_suggest': '60-70%'
        },
        'greed': {
            'action': '逐步减仓',
            'description': '市场情绪偏乐观，注意获利了结，避免追高',
            'risk_level': '中高',
            'position_suggest': '50-60%'
        },
        'extreme_greed': {
            'action': '减仓避险',
            'description': '市场情绪极度乐观，泡沫风险增加，建议减仓避险',
            'risk_level': '高',
            'position_suggest': '30-50%'
        }
    }
    
    def __init__(self):
        self.weights = {
            'index_change': 0.25,      # 指数涨跌权重
            'up_down_ratio': 0.20,      # 涨跌家数比权重
            'limit_up_down': 0.20,      # 涨跌停数量权重
            'fund_flow': 0.20,          # 资金流向权重
            'hot_stock_momentum': 0.15  # 热门股动量权重
        }
    
    def calculate_sentiment_index(self, data: Dict) -> Tuple[int, str, Dict]:
        """
        计算市场情绪指数 (0-100)
        
        Returns:
            (指数值, 情绪级别key, 详细分析数据)
        """
        scores = {}
        details = {}
        
        # 1. 指数涨跌幅评分 (0-25分)
        index_score = self._calc_index_score(data.get('market_overview', {}))
        scores['index_change'] = index_score
        details['index_change'] = {'score': index_score, 'max': 25, 'weight': 0.25}
        
        # 2. 涨跌家数比评分 (0-20分)
        up_down_score = self._calc_up_down_score(data)
        scores['up_down_ratio'] = up_down_score
        details['up_down_ratio'] = {'score': up_down_score, 'max': 20, 'weight': 0.20}
        
        # 3. 涨跌停数量评分 (0-20分)
        limit_score = self._calc_limit_score(data.get('limit_stats', {}))
        scores['limit_up_down'] = limit_score
        details['limit_up_down'] = {'score': limit_score, 'max': 20, 'weight': 0.20}
        
        # 4. 资金流向评分 (0-20分)
        fund_score = self._calc_fund_score(data.get('fund_flow', {}))
        scores['fund_flow'] = fund_score
        details['fund_flow'] = {'score': fund_score, 'max': 20, 'weight': 0.20}
        
        # 5. 热门股动量评分 (0-15分)
        momentum_score = self._calc_momentum_score(data.get('hot_stocks', []))
        scores['hot_stock_momentum'] = momentum_score
        details['hot_stock_momentum'] = {'score': momentum_score, 'max': 15, 'weight': 0.15}
        
        # 计算总分
        total_score = sum(scores.values())
        
        # 确保在0-100范围内
        sentiment_index = max(0, min(100, int(total_score * 2)))
        
        # 确定情绪级别
        level_key = self._get_sentiment_level(sentiment_index)
        
        return sentiment_index, level_key, {
            'scores': scores,
            'details': details,
            'raw_total': total_score
        }
    
    def _calc_index_score(self, market_overview: Dict) -> float:
        """根据指数涨跌幅计算得分 (0-25)"""
        if not market_overview:
            return 12.5  # 中性
        
        # 取上证指数作为代表
        sh_index = market_overview.get('sh', {})
        change_pct = sh_index.get('change_percent', 0)
        
        # 转换得分: -2% -> 0分, 0% -> 12.5分, +2% -> 25分
        score = 12.5 + (change_pct / 2) * 12.5
        return max(0, min(25, score))
    
    def _calc_up_down_score(self, data: Dict) -> float:
        """根据涨跌家数比计算得分 (0-20)"""
        # 简化计算，实际应从数据中解析
        market = data.get('market_overview', {})
        
        # 如果有涨跌幅信息，进行估算
        if market:
            sh_change = market.get('sh', {}).get('change_percent', 0)
            # 估算涨跌比
            if sh_change > 1:
                return 18  # 普涨
            elif sh_change > 0.5:
                return 15
            elif sh_change > 0:
                return 12
            elif sh_change > -0.5:
                return 8
            elif sh_change > -1:
                return 5
            else:
                return 3
        
        return 10  # 默认值
    
    def _calc_limit_score(self, limit_stats: Dict) -> float:
        """根据涨跌停数量计算得分 (0-20)"""
        limit_up = limit_stats.get('limit_up_count', 0)
        limit_down = limit_stats.get('limit_down_count', 0)
        
        if limit_up + limit_down == 0:
            return 10
        
        # 涨停多=贪婪，跌停多=恐慌
        ratio = limit_up / (limit_up + limit_down + 1)
        score = ratio * 20
        
        # 调整：如果跌停太多，扣分
        if limit_down > 50:
            score -= 5
        
        return max(0, min(20, score))
    
    def _calc_fund_score(self, fund_flow: Dict) -> float:
        """根据资金流向计算得分 (0-20)"""
        north_inflow = fund_flow.get('north_inflow', 0)
        
        # 北向资金流入为正，得分高
        # 50亿流入 = 20分，0 = 10分，-50亿 = 0分
        score = 10 + (north_inflow / 50) * 10
        return max(0, min(20, score))
    
    def _calc_momentum_score(self, hot_stocks: List[Dict]) -> float:
        """根据热门股动量计算得分 (0-15)"""
        if not hot_stocks:
            return 7.5
        
        # 计算平均涨跌幅
        total_change = sum(s.get('change_percent', 0) for s in hot_stocks)
        avg_change = total_change / len(hot_stocks)
        
        # 平均涨幅3% = 15分，0% = 7.5分，-3% = 0分
        score = 7.5 + (avg_change / 3) * 7.5
        return max(0, min(15, score))
    
    def _get_sentiment_level(self, index: int) -> str:
        """根据情绪指数获取级别"""
        for key, (min_val, max_val, _, _) in self.SENTIMENT_LEVELS.items():
            if min_val <= index < max_val:
                return key
        return 'neutral'
    
    def get_sentiment_description(self, index: int, level_key: str) -> Dict:
        """获取情绪描述"""
        _, _, name, emoji = self.SENTIMENT_LEVELS.get(level_key, ('', '', '未知', '⚪'))
        
        return {
            'index': index,
            'level': name,
            'emoji': emoji,
            'level_key': level_key
        }
    
    def get_trading_advice(self, level_key: str) -> Dict:
        """获取交易建议"""
        advice = self.ADVICE_CONFIG.get(level_key, self.ADVICE_CONFIG['neutral'])
        return advice
    
    def generate_risk_warnings(self, data: Dict, sentiment_index: int) -> List[str]:
        """生成风险提示"""
        warnings = []
        
        market = data.get('market_overview', {})
        limit_stats = data.get('limit_stats', {})
        fund_flow = data.get('fund_flow', {})
        
        # 指数大跌风险
        sh_change = market.get('sh', {}).get('change_percent', 0)
        if sh_change < -1.5:
            warnings.append(f"⚠️ 上证指数大跌 {sh_change:.2f}%，注意系统性风险")
        
        # 跌停过多
        limit_down = limit_stats.get('limit_down_count', 0)
        if limit_down > 30:
            warnings.append(f"🔴 跌停家数达 {limit_down} 家，恐慌情绪蔓延")
        
        # 北向大幅流出
        north_inflow = fund_flow.get('north_inflow', 0)
        if north_inflow < -30:
            warnings.append(f"💸 北向资金大幅流出 {abs(north_inflow):.1f} 亿，外资看空")
        
        # 情绪极端
        if sentiment_index < 15:
            warnings.append("📉 情绪指数极低，短期或有反弹，但需警惕持续下跌")
        elif sentiment_index > 85:
            warnings.append("📈 情绪指数极高，注意获利了结，防范回调风险")
        
        if not warnings:
            warnings.append("✅ 当前无明显系统性风险")
        
        return warnings
    
    def analyze(self, data: Dict) -> Dict:
        """
        执行完整分析
        
        Returns:
            完整的分析报告
        """
        # 计算情绪指数
        sentiment_index, level_key, calc_details = self.calculate_sentiment_index(data)
        
        # 获取描述和建议
        sentiment_desc = self.get_sentiment_description(sentiment_index, level_key)
        advice = self.get_trading_advice(level_key)
        warnings = self.generate_risk_warnings(data, sentiment_index)
        
        return {
            'sentiment_index': sentiment_index,
            'sentiment_level': sentiment_desc,
            'advice': advice,
            'risk_warnings': warnings,
            'calculation_details': calc_details,
            'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


# 测试代码
if __name__ == '__main__':
    analyzer = SentimentAnalyzer()
    
    # 模拟数据
    test_data = {
        'market_overview': {
            'sh': {'change_percent': -0.85},
            'sz': {'change_percent': -0.62},
            'cy': {'change_percent': -1.23}
        },
        'limit_stats': {'limit_up_count': 45, 'limit_down_count': 12},
        'fund_flow': {'north_inflow': -15.5},
        'hot_stocks': [
            {'change_percent': 5.2},
            {'change_percent': 3.8},
            {'change_percent': -2.1}
        ]
    }
    
    result = analyzer.analyze(test_data)
    print(json.dumps(result, ensure_ascii=False, indent=2))