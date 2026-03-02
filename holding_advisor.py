#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持有时间建议器 - 基于波动率和趋势强度计算建议持有天数
"""

import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime, timedelta

try:
    import akshare as ak
except ImportError:
    ak = None


class HoldingAdvisor:
    """持有时间建议器"""
    
    # 持有时间档位
    HOLDING_PERIODS = {
        'short': {
            'name': '短线',
            'days_range': (1, 3),
            'description': '超短线操作，快进快出'
        },
        'medium_short': {
            'name': '中短线', 
            'days_range': (3, 7),
            'description': '波段操作，把握短期趋势'
        },
        'medium': {
            'name': '中线',
            'days_range': (7, 15),
            'description': '中期持有，等待主升浪'
        }
    }
    
    # 评分阈值
    THRESHOLDS = {
        'high_volatility': 3.0,      # 高波动率阈值(%)
        'low_volatility': 1.5,       # 低波动率阈值(%)
        'strong_trend': 2.0,         # 强趋势阈值(%)
        'weak_trend': 0.5            # 弱趋势阈值(%)
    }
    
    def __init__(self):
        pass
    
    def calculate_holding_period(self, stock: Dict, historical_data: List[Dict] = None) -> Dict:
        """
        计算建议持有时间
        
        Args:
            stock: 股票基本信息
            historical_data: 历史数据（可选）
            
        Returns:
            持有建议字典
        """
        # 1. 计算波动率得分
        volatility_score = self._calc_volatility_score(stock, historical_data)
        
        # 2. 计算趋势强度得分
        trend_score = self._calc_trend_score(stock, historical_data)
        
        # 3. 计算情绪稳定性得分
        stability_score = self._calc_stability_score(stock)
        
        # 4. 综合评分确定持有时间
        holding_period = self._determine_holding_period(
            volatility_score, trend_score, stability_score
        )
        
        # 5. 生成建议说明
        advice = self._generate_advice(
            holding_period, volatility_score, trend_score, stock
        )
        
        return {
            'stock_code': stock.get('code'),
            'stock_name': stock.get('name'),
            'suggested_days': holding_period['days_range'],
            'suggested_days_str': f"{holding_period['days_range'][0]}-{holding_period['days_range'][1]}天",
            'period_type': holding_period['type'],
            'period_name': holding_period['name'],
            'description': holding_period['description'],
            'volatility_score': round(volatility_score, 2),
            'trend_score': round(trend_score, 2),
            'stability_score': round(stability_score, 2),
            'detailed_advice': advice,
            'stop_loss_suggest': self._calc_stop_loss(stock, volatility_score),
            'take_profit_suggest': self._calc_take_profit(stock, trend_score)
        }
    
    def _calc_volatility_score(self, stock: Dict, historical_data: List[Dict] = None) -> float:
        """
        计算波动率得分 (0-1，越高越波动)
        基于：换手率、振幅、量比
        """
        turnover = stock.get('turnover', 0)  # 换手率
        change = abs(stock.get('change_percent', 0))  # 涨跌幅绝对值
        volume_ratio = stock.get('volume_ratio', 2)  # 量比，默认2
        
        # 换手率得分 (0-0.4)
        turnover_score = min(turnover / 20, 1.0) * 0.4
        
        # 涨跌幅得分 (0-0.35)
        change_score = min(change / 10, 1.0) * 0.35
        
        # 量比得分 (0-0.25)
        ratio_score = min(volume_ratio / 5, 1.0) * 0.25
        
        return turnover_score + change_score + ratio_score
    
    def _calc_trend_score(self, stock: Dict, historical_data: List[Dict] = None) -> float:
        """
        计算趋势强度得分 (0-1，越高趋势越强)
        基于：当日涨幅、情绪得分
        """
        change = stock.get('change_percent', 0)
        sentiment = stock.get('sentiment_score', 50)
        
        # 涨幅得分 (0-0.5)
        # 3-7%涨幅得分最高，超过9%可能是涨停，次日可能分化
        if change <= 3:
            change_score = change / 6  # 0-3% -> 0-0.5
        elif change <= 7:
            change_score = 0.5 + (change - 3) / 8  # 3-7% -> 0.5-1.0
        else:
            change_score = 1.0 - (change - 7) / 10  # >7% 开始递减
        
        change_score = max(0, min(0.5, change_score))
        
        # 情绪得分 (0-0.5)
        sentiment_score = sentiment / 200  # 0-100分 -> 0-0.5
        
        return change_score + sentiment_score
    
    def _calc_stability_score(self, stock: Dict) -> float:
        """
        计算情绪稳定性得分 (0-1，越高越稳定)
        基于：成交额、市值
        """
        amount = stock.get('amount', 1)  # 成交额(亿)
        
        # 成交额越大，情绪越稳定 (0-1)
        stability = min(amount / 10, 1.0) * 0.7 + 0.3
        
        return stability
    
    def _determine_holding_period(self, volatility: float, trend: float, stability: float) -> Dict:
        """
        根据评分确定持有时间档位
        
        逻辑：
        - 高波动 + 强趋势 = 短线 (1-3天)，快进快出
        - 中波动 + 中趋势 = 中短线 (3-7天)，波段操作  
        - 低波动 + 强趋势 = 中线 (7-15天)，趋势跟踪
        """
        # 综合评分
        # 波动率越高，持有时间越短
        # 趋势越强，持有时间可以适当延长
        # 稳定性越高，持有时间可以适当延长
        
        weighted_score = (
            (1 - volatility) * 0.4 +  # 低波动偏好长期
            trend * 0.35 +              # 强趋势可以持有多久
            stability * 0.25           # 高稳定性偏好长期
        )
        
        if weighted_score < 0.4:
            # 高波动或弱趋势，短线操作
            period = self.HOLDING_PERIODS['short'].copy()
            period['type'] = 'short'
        elif weighted_score < 0.7:
            # 平衡状态，中短线操作
            period = self.HOLDING_PERIODS['medium_short'].copy()
            period['type'] = 'medium_short'
        else:
            # 低波动强趋势，中线操作
            period = self.HOLDING_PERIODS['medium'].copy()
            period['type'] = 'medium'
        
        return period
    
    def _generate_advice(self, period: Dict, volatility: float, trend: float, stock: Dict) -> str:
        """生成详细建议"""
        parts = []
        
        # 基于波动率的建议
        if volatility > 0.6:
            parts.append("该股波动较大，建议严格设置止损")
        elif volatility < 0.3:
            parts.append("该股走势相对稳健")
        
        # 基于趋势的建议
        change = stock.get('change_percent', 0)
        if change > 7:
            parts.append("当日涨幅较大，注意次日分化风险")
        elif change > 3:
            parts.append("启动迹象明显，可关注延续性")
        
        # 基于持有时间的建议
        if period['type'] == 'short':
            parts.append(f"建议{period['days_range'][0]}-{period['days_range'][1]}天内完成交易")
        elif period['type'] == 'medium':
            parts.append(f"可中期持有{period['days_range'][0]}-{period['days_range'][1]}天")
        
        return "；".join(parts) if parts else "建议根据个人风险承受能力操作"
    
    def _calc_stop_loss(self, stock: Dict, volatility: float) -> str:
        """计算建议止损位"""
        change = stock.get('change_percent', 0)
        
        # 基于波动率设置止损
        if volatility > 0.6:
            stop_pct = 5  # 高波动，5%止损
        elif volatility > 0.4:
            stop_pct = 4  # 中波动，4%止损
        else:
            stop_pct = 3  # 低波动，3%止损
        
        # 如果已大涨，调整止损
        if change > 5:
            stop_pct = min(stop_pct, 3)
        
        return f"-{stop_pct}%"
    
    def _calc_take_profit(self, stock: Dict, trend: float) -> str:
        """计算建议止盈位"""
        change = stock.get('change_percent', 0)
        
        # 基于趋势强度设置止盈
        if trend > 0.7:
            profit_pct = 15  # 强趋势，看高一线
        elif trend > 0.5:
            profit_pct = 10  # 中趋势，10%止盈
        else:
            profit_pct = 7   # 弱趋势，7%止盈
        
        return f"+{profit_pct}%"
    
    def advise_batch(self, stocks: List[Dict]) -> List[Dict]:
        """
        批量计算持有建议
        
        Returns:
            带有持有建议的股票列表
        """
        result = []
        
        for stock in stocks:
            advice = self.calculate_holding_period(stock)
            
            # 合并原始数据和建议
            stock_with_advice = stock.copy()
            stock_with_advice.update({
                'suggested_hold_days': advice['suggested_days_str'],
                'holding_advice': advice['detailed_advice'],
                'stop_loss': advice['stop_loss_suggest'],
                'take_profit': advice['take_profit_suggest'],
                'volatility_score': advice['volatility_score'],
                'trend_score': advice['trend_score']
            })
            
            result.append(stock_with_advice)
        
        return result


# 测试代码
if __name__ == '__main__':
    advisor = HoldingAdvisor()
    
    # 模拟股票数据
    test_stocks = [
        {'code': '000001', 'name': '平安银行', 'change_percent': 5.2, 'turnover': 8.5, 'amount': 15.2, 'sentiment_score': 82},
        {'code': '000002', 'name': '万科A', 'change_percent': 2.1, 'turnover': 3.2, 'amount': 8.5, 'sentiment_score': 68},
        {'code': '600519', 'name': '贵州茅台', 'change_percent': 1.5, 'turnover': 0.8, 'amount': 25.0, 'sentiment_score': 75}
    ]
    
    print("📊 持有时间建议测试：\n")
    
    for stock in test_stocks:
        advice = advisor.calculate_holding_period(stock)
        print(f"\n{advice['stock_name']}({advice['stock_code']}):")
        print(f"  建议持有: {advice['suggested_days_str']}")
        print(f"  止损位: {advice['stop_loss_suggest']} | 止盈位: {advice['take_profit_suggest']}")
        print(f"  建议: {advice['detailed_advice']}")
