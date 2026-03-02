#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书推送模块 - 发送情绪分析报告到飞书
"""

import json
import requests
from datetime import datetime
from typing import Dict, List, Optional


class FeishuPusher:
    """飞书消息推送器"""
    
    def __init__(self, webhook_url: Optional[str] = None, secret: Optional[str] = None):
        self.webhook_url = webhook_url
        self.secret = secret
    
    def set_webhook(self, url: str, secret: Optional[str] = None):
        """设置 webhook 地址"""
        self.webhook_url = url
        if secret:
            self.secret = secret
    
    def format_report(self, market_data: Dict, analysis: Dict, top_stocks: List[Dict] = None) -> str:
        """格式化报告内容（适合手机查看）"""
        now = datetime.now()
        date_str = now.strftime('%m月%d日')
        time_str = now.strftime('%H:%M')
        
        sentiment = analysis.get('sentiment_level', {})
        advice = analysis.get('advice', {})
        
        lines = [
            f"# 📊 A股情绪晨间预警 | {date_str}",
            "",
            f"⏰ 更新时间：{time_str}",
            "",
            "---",
            "",
            "## 🎯 市场情绪指数",
            "",
            f"### {sentiment.get('emoji', '⚪')} {sentiment.get('index', 50)} 分 - {sentiment.get('level', '中性')}",
            "",
            "---",
            "",
            "## 📈 市场概况",
            ""
        ]
        
        # 添加指数信息
        market = market_data.get('market_overview', {})
        for idx_key, idx_info in [('sh', '上证指数'), ('sz', '深证成指'), ('cy', '创业板指')]:
            idx_data = market.get(idx_key, {})
            if idx_data:
                change_pct = idx_data.get('change_percent', 0)
                emoji = "📈" if change_pct > 0 else "📉" if change_pct < 0 else "➖"
                lines.append(f"{emoji} **{idx_info}**: {idx_data.get('price', 0):.2f} ({change_pct:+.2f}%)")
        
        lines.extend([
            "",
            "---",
            "",
            "## 💡 操作建议",
            "",
            f"**{advice.get('action', '观望')}**",
            "",
            f"⚖️ 风险等级: {advice.get('risk_level', '中')} | 📊 建议仓位: {advice.get('position_suggest', '60%')}",
            "",
            "---",
            "",
            "## 🔥 热门板块",
            ""
        ])
        
        # 添加热门板块
        hot_sectors = market_data.get('hot_sectors', [])
        for i, sector in enumerate(hot_sectors[:5], 1):
            change = sector.get('change_percent', 0)
            emoji = "🔺" if change > 0 else "🔻" if change < 0 else "➖"
            lines.append(f"{i}. {emoji} **{sector.get('name', '未知')}** {change:+.2f}%")
        
        # 添加TOP5选股推荐
        if top_stocks:
            lines.extend([
                "",
                "---",
                "",
                "## 📈 今日情绪选股TOP5",
                ""
            ])
            
            medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
            for i, stock in enumerate(top_stocks[:5], 1):
                medal = medals[i-1] if i <= 3 else f"{i}."
                name = stock.get('name', '未知')
                code = stock.get('code', '')
                score = stock.get('sentiment_score', 0)
                hold_days = stock.get('suggested_hold_days', '2-4天')
                lines.append(f"{medal} **{name}({code})** | 情绪分: {score} | 建议持有: {hold_days}")
        
        lines.extend([
            "",
            "---",
            "",
            "## ⚠️ 风险提示",
            ""
        ])
        
        # 添加风险提示
        warnings = analysis.get('risk_warnings', [])
        if warnings:
            for warning in warnings[:3]:
                lines.append(f"• {warning}")
        else:
            lines.append("• ✅ 当前无明显系统性风险")
        
        lines.extend([
            "",
            "---",
            "",
            "*⚠️ 免责声明：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。*"
        ])
        
        return "\n".join(lines)
    
    def send_text(self, content: str) -> bool:
        """发送文本消息"""
        if not self.webhook_url:
            print("❌ Webhook URL 未设置")
            return False
        
        payload = {
            "msg_type": "text",
            "content": {"text": content}
        }
        
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            result = resp.json()
            
            if result.get('code') == 0:
                print("✅ 消息发送成功")
                return True
            else:
                print(f"❌ 发送失败: {result}")
                return False
                
        except Exception as e:
            print(f"❌ 发送异常: {e}")
            return False
    
    def send_report(self, market_data: Dict, analysis: Dict, top_stocks: List[Dict] = None) -> bool:
        """发送完整报告"""
        content = self.format_report(market_data, analysis, top_stocks)
        return self.send_text(content)


# 测试代码
if __name__ == '__main__':
    pusher = FeishuPusher()
    print("飞书推送模块已加载")
    print("请设置 webhook_url 后使用")
