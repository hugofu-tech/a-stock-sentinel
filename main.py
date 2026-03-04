#!/usr/bin/env python3
"""
A股情绪晨间预警系统 - V2.0 专业版
基于多维度情绪选股模型
技术60% + 资金25% + 情绪15%
"""

import os
import sys
import json
import requests
import baostock as bs
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

# 飞书配置
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
FEISHU_TARGET = os.environ.get('FEISHU_TARGET', 'user:ou_0ad234b6ebfca4f424bd582393734d0f')

# 设置北京时区
beijing_tz = pytz.timezone('Asia/Shanghai')

def get_trade_date():
    """获取当前交易日期（北京时间）
    如果在开盘前，返回上一个交易日
    """
    now = datetime.now(beijing_tz)
    
    # 如果是周末，返回周五
    if now.weekday() >= 5:  # 周六=5, 周日=6
        days_back = now.weekday() - 4  # 周六→1天前(周五), 周日→2天前(周五)
        trade_date = now - timedelta(days=days_back)
        return trade_date.strftime('%Y-%m-%d')
    
    # 如果是工作日但开盘前(9:30前)，返回上一个交易日
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        if now.weekday() == 0:  # 周一开盘前，返回上周五
            trade_date = now - timedelta(days=3)
        else:
            trade_date = now - timedelta(days=1)
        return trade_date.strftime('%Y-%m-%d')
    
    return now.strftime('%Y-%m-%d')


class ProfessionalSentimentModel:
    """
    专业情绪评分模型 V2.0
    多维度加权评分体系
    """
    
    def calculate_score(self, stock):
        """计算综合情绪得分 (0-100)"""
        
        # 技术面得分 (0-60)
        technical = self._technical_score(stock)
        
        # 资金面得分 (0-25)
        capital = self._capital_score(stock)
        
        # 情绪面得分 (0-15)
        sentiment = self._sentiment_score(stock)
        
        # 加权综合
        total = technical * 0.60 + capital * 0.25 + sentiment * 0.15
        
        return {
            'total_score': round(total, 1),
            'technical': round(technical, 1),
            'capital': round(capital, 1),
            'sentiment': round(sentiment, 1)
        }
    
    def _technical_score(self, stock):
        """技术面评分 (0-60分)"""
        score = 0
        
        # 1. 涨幅评分 (0-20分) - 非线性
        change = stock.get('change', 0)
        if change >= 9.9:
            score += 20  # 涨停
        elif change >= 5:
            score += 15 + (change - 5) * 0.8
        elif change >= 2:
            score += 10 + (change - 2) * 1.67
        elif change > 0:
            score += change * 5
        elif change >= -2:
            score += max(0, 5 + change * 2.5)
        
        # 2. 量比评分 (0-15分)
        vol_ratio = stock.get('volume_ratio', 1)
        if vol_ratio >= 3:
            score += 15
        elif vol_ratio >= 1.5:
            score += 10 + (vol_ratio - 1.5) * 6.67
        elif vol_ratio >= 0.8:
            score += (vol_ratio - 0.8) * 11.9
        
        # 3. 换手率评分 (0-15分)
        turnover = stock.get('turnover', 0)
        if turnover >= 20:
            score += 15
        elif turnover >= 10:
            score += 10 + (turnover - 10) * 0.5
        elif turnover >= 3:
            score += 5 + (turnover - 3) * 0.71
        elif turnover >= 1:
            score += (turnover - 1) * 2.5
        
        # 4. 成交额评分 (0-10分)
        amount = stock.get('amount', 0)
        if amount >= 10:  # 10亿+
            score += 10
        elif amount >= 5:
            score += 7 + (amount - 5) * 0.6
        elif amount >= 1:
            score += 3 + (amount - 1) * 1
        
        return min(60, score)
    
    def _capital_score(self, stock):
        """资金面评分 (0-25分)"""
        score = 0
        
        # 资金强度 = 量比*0.6 + 换手率*0.4
        vol_ratio = stock.get('volume_ratio', 1)
        turnover = stock.get('turnover', 0)
        strength = (vol_ratio * 0.6 + turnover * 0.4) / 10
        
        if strength >= 2:
            score += 15
        elif strength >= 1:
            score += 7.5 + (strength - 1) * 7.5
        else:
            score += strength * 7.5
        
        # 量价配合
        change = stock.get('change', 0)
        if change > 0 and vol_ratio > 1.5:
            score += 10
        elif change > 0 and vol_ratio > 1:
            score += 7
        elif change > 0:
            score += 5
        
        return min(25, score)
    
    def _sentiment_score(self, stock):
        """情绪面评分 (0-15分)"""
        change = stock.get('change', 0)
        
        if change >= 9.9:
            return 15
        elif change >= 7:
            return 13
        elif change >= 5:
            return 11
        elif change >= 3:
            return 9
        elif change >= 1:
            return 6 + change * 0.5
        elif change >= -1:
            return max(0, 3 + change * 3)
        elif change >= -3:
            return max(0, 1.5 + (change + 3) * 0.75)
        
        return 0


def get_signal(score_data):
    """生成买卖信号"""
    total = score_data['total_score']
    technical = score_data['technical']
    
    if total >= 75 and technical >= 45:
        return "🔴 STRONG BUY", "强烈买入"
    elif total >= 60 and technical >= 35:
        return "🟢 BUY", "买入"
    elif total >= 45:
        return "🟡 WATCH", "关注"
    elif total >= 30:
        return "⚪ HOLD", "持有"
    else:
        return "❄️ AVOID", "回避"


def get_feishu_token():
    """获取飞书token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    data = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=30)
        result = resp.json()
        if result.get('code') == 0:
            return result['tenant_access_token']
    except Exception as e:
        print(f"Token error: {e}")
    return None


def send_feishu_message(content):
    """发送飞书消息"""
    token = get_feishu_token()
    if not token:
        return False
    
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"receive_id_type": "open_id"}
    
    receive_id = FEISHU_TARGET.replace('user:', '')
    data = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": content})
    }
    
    try:
        resp = requests.post(url, json=data, headers=headers, params=params, timeout=30)
        return resp.json().get('code') == 0
    except Exception as e:
        print(f"Send error: {e}")
        return False


def get_market_data():
    """获取市场数据"""
    lg = bs.login()
    if lg.error_code != '0':
        return {}
    
    trade_date = get_trade_date()
    today_str = datetime.now(beijing_tz).strftime('%Y-%m-%d')
    
    print(f"📅 交易日期: {trade_date} (今天: {today_str})")
    
    indices = {}
    
    for code, key, name in [
        ("sh.000001", "sh", "上证指数"),
        ("sz.399001", "sz", "深证成指"),
        ("sz.399006", "cy", "创业板指")
    ]:
        rs = bs.query_history_k_data_plus(code, "close,pctChg",
            start_date=trade_date, end_date=trade_date)
        if rs.error_code == '0' and rs.next():
            data = rs.get_row_data()
            indices[key] = {
                'name': name,
                'value': float(data[0]),
                'change': float(data[1])
            }
        else:
            print(f"⚠️  {name} 数据未获取")
    
    bs.logout()
    return indices


def get_stock_data():
    """获取股票数据并选股"""
    lg = bs.login()
    if lg.error_code != '0':
        return []
    
    trade_date = get_trade_date()
    print(f"🔍 扫描 {trade_date} 的数据...")
    
    # 获取A股列表
    rs = bs.query_all_stock(day=trade_date)
    stock_list = []
    count = 0
    
    while rs.error_code == '0' and rs.next() and count < 800:
        row = rs.get_row_data()
        code = row[0]  # 格式: sh.600000 或 sz.000001
        
        # 精确过滤：只选A股个股
        # 沪市: 600/601/603/605(主板), 688(科创)
        # 深市: 000/001/002/003(主板), 300/301(创业)
        is_sh_stock = (
            code.startswith('sh.600') or 
            code.startswith('sh.601') or 
            code.startswith('sh.603') or
            code.startswith('sh.605') or
            code.startswith('sh.688')
        )
        is_sz_stock = (
            code.startswith('sz.000') or
            code.startswith('sz.001') or
            code.startswith('sz.002') or
            code.startswith('sz.003') or
            code.startswith('sz.300') or
            code.startswith('sz.301')
        )
        
        if not (is_sh_stock or is_sz_stock):
            continue  # 跳过指数、ETF、债券等
        
        # 获取行情
        rs_k = bs.query_history_k_data_plus(code,
            "code,close,preclose,pctChg,volume,amount,turn",
            start_date=today, end_date=today)
        
        if rs_k.error_code == '0' and rs_k.next():
            data = rs_k.get_row_data()
            try:
                change = float(data[3])
                turnover = float(data[6])
                amount = float(data[5]) / 100000000  # 亿
                
                # 基础筛选
                if 0 < change < 15 and amount > 0.5 and turnover > 1:
                    # 获取名称
                    rs_name = bs.query_stock_basic(code=code)
                    name = code
                    if rs_name.error_code == '0' and rs_name.next():
                        name = rs_name.get_row_data()[1]
                    
                    # 计算量比 (简化：用换手率近似)
                    volume_ratio = turnover / 3  # 假设平均换手3%
                    
                    stock_list.append({
                        'name': name,
                        'code': code,
                        'price': float(data[1]),
                        'change': change,
                        'turnover': turnover,
                        'volume_ratio': volume_ratio,
                        'amount': amount
                    })
            except:
                pass
        
        count += 1
    
    bs.logout()
    return stock_list


def main():
    # 使用北京时间
    now = datetime.now(beijing_tz)
    trade_date = get_trade_date()
    
    print("🚀 A股情绪晨间预警 V2.0 专业版")
    print("="*60)
    print(f"⏰ 北京时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📅 交易日期: {trade_date}\n")
    
    # 开盘前提醒
    if trade_date != now.strftime('%Y-%m-%d'):
        print("🌙 当前为开盘前，使用上一交易日数据\n")
    
    # 初始化模型
    model = ProfessionalSentimentModel()
    
    # 获取市场数据
    print("📊 获取市场数据...")
    market = get_market_data()
    print(f"✅ {len(market)} 个指数")
    
    # 获取股票
    print("\n🔍 全市场扫描...")
    stocks = get_stock_data()
    print(f"✅ {len(stocks)} 只股票通过初筛")
    
    # 评分
    print("\n🎯 专业情绪评分...")
    scored_stocks = []
    for stock in stocks:
        score_data = model.calculate_score(stock)
        signal, desc = get_signal(score_data)
        
        scored_stocks.append({
            **stock,
            **score_data,
            'signal': signal,
            'signal_desc': desc
        })
    
    # 排序取前5
    scored_stocks.sort(key=lambda x: x['total_score'], reverse=True)
    top5 = scored_stocks[:5]
    
    # 生成报告
    print("\n📝 生成报告...")
    report_time = now.strftime('%m月%d日 %H:%M')
    
    market_text = ""
    for key in ['sh', 'sz', 'cy']:
        if key in market:
            m = market[key]
            emoji = "📈" if m['change'] >= 0 else "📉"
            market_text += f"{emoji} {m['name']}: {m['value']:.2f} ({m['change']:+.2f}%)\n"
    
    stock_text = ""
    for i, s in enumerate(top5, 1):
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
        
        stock_text += f"{emoji} {s['name']}({s['code']})\n"
        stock_text += f"   价格: ¥{s['price']:.2f} | 涨幅: {s['change']:+.2f}% | 换手: {s['turnover']:.1f}%\n"
        stock_text += f"   📊 综合: {s['total_score']:.1f} | 技术: {s['technical']:.1f} | 资金: {s['capital']:.1f} | 情绪: {s['sentiment']:.1f}\n"
        stock_text += f"   💡 信号: {s['signal']} ({s['signal_desc']})\n\n"
    
    report = f"""📊 A股情绪晨间预警 V2.0 | {report_time}

📈 市场概况
{market_text}
🎯 情绪选股TOP5 (专业版)
{stock_text}
📊 V2.0评分体系:
• 技术面60%: 涨幅+量比+换手+成交额
• 资金面25%: 资金强度+量价配合  
• 情绪面15%: 市场情绪传导

⚠️ 免责声明：仅供参考，不构成投资建议。"""
    
    print(report[:800] + "...")
    
    # 保存并发送 - 使用实际日期命名文件
    filename = f'report_v2_{now.strftime("%Y%m%d")}.md'
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n📄 已保存: {filename}")
    
    # 发送到飞书
    if FEISHU_APP_ID and FEISHU_APP_SECRET:
        print("\n📤 发送到飞书...")
        if send_feishu_message(report):
            print("✅ 发送成功!")
        else:
            print("❌ 发送失败")
    else:
        print("\n⚠️  未配置飞书凭据，跳过发送")
        print(report)


if __name__ == "__main__":
    main()
