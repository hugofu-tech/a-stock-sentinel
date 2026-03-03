#!/usr/bin/env python3
"""
A股情绪晨间预警系统 - Baostock版本
解决akshare连接问题
"""

import os
import sys
import json
import requests
import baostock as bs
import pandas as pd
from datetime import datetime

# 飞书配置从环境变量读取
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
FEISHU_TARGET = os.environ.get('FEISHU_TARGET', 'user:ou_0ad234b6ebfca4f424bd582393734d0f')


def get_feishu_token():
    """获取飞书access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    data = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=30)
        result = resp.json()
        if result.get('code') == 0:
            return result['tenant_access_token']
        else:
            print(f"获取token失败: {result}")
            return None
    except Exception as e:
        print(f"获取token异常: {e}")
        return None


def send_feishu_message(content, msg_type="text"):
    """发送飞书消息"""
    token = get_feishu_token()
    if not token:
        print("❌ 无法获取飞书token")
        return False
    
    receive_id_type = 'open_id'
    receive_id = FEISHU_TARGET.replace('user:', '')
    
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"receive_id_type": receive_id_type}
    
    message_content = json.dumps({"text": content})
    data = {
        "receive_id": receive_id,
        "msg_type": msg_type,
        "content": message_content
    }
    
    try:
        resp = requests.post(url, json=data, headers=headers, params=params, timeout=30)
        result = resp.json()
        if result.get('code') == 0:
            print(f"✅ 飞书消息发送成功")
            return True
        else:
            print(f"❌ 发送失败: {result.get('msg', result)}")
            return False
    except Exception as e:
        print(f"❌ 发送异常: {e}")
        return False


def get_market_overview():
    """获取市场概况 - 使用Baostock"""
    try:
        lg = bs.login()
        if lg.error_code != '0':
            print(f"登录失败: {lg.error_msg}")
            return {}
        
        today = datetime.now().strftime('%Y-%m-%d')
        indices = {}
        
        # 主要指数代码映射
        index_codes = [
            ("sh.000001", "sh", "上证指数"),
            ("sz.399001", "sz", "深证成指"),
            ("sz.399006", "cy", "创业板指")
        ]
        
        for code, key, name in index_codes:
            rs = bs.query_history_k_data_plus(code,
                "date,close,pctChg",
                start_date=today, end_date=today)
            
            if rs.error_code == '0' and rs.next():
                data = rs.get_row_data()
                indices[key] = {
                    'name': name,
                    'value': float(data[1]),
                    'change': float(data[2])
                }
        
        bs.logout()
        return indices
    except Exception as e:
        print(f"获取市场概况失败: {e}")
        return {}


def get_stock_screener():
    """全A股筛选 - 使用Baostock"""
    try:
        lg = bs.login()
        if lg.error_code != '0':
            return []
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 获取所有A股代码
        rs = bs.query_all_stock(day=today)
        if rs.error_code != '0':
            bs.logout()
            return []
        
        stock_list = []
        while rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            code = row[0]  # 股票代码
            
            # 获取每只股票今日行情
            rs_k = bs.query_history_k_data_plus(code,
                "code,close,preclose,pctChg,volume,amount,turn",
                start_date=today, end_date=today)
            
            if rs_k.error_code == '0' and rs_k.next():
                data = rs_k.get_row_data()
                try:
                    change = float(data[3])
                    volume = float(data[4])
                    amount = float(data[5])
                    turnover = float(data[6])
                    
                    # 筛选条件
                    if abs(change) < 15 and amount > 50000000 and change > 0:
                        # 获取股票名称
                        rs_name = bs.query_stock_basic(code=code)
                        name = code
                        if rs_name.error_code == '0' and rs_name.next():
                            name = rs_name.get_row_data()[1]  # 股票名称
                        
                        # 情绪分 = 涨幅 * 换手率
                        score = change * turnover
                        
                        stock_list.append({
                            'name': name,
                            'code': code,
                            'price': float(data[1]),
                            'change': change,
                            'turnover': turnover,
                            'amount': amount / 100000000,
                            'score': round(score, 2)
                        })
                except:
                    continue
            
            # 限制查询数量，避免太慢
            if len(stock_list) > 100:
                break
        
        bs.logout()
        
        # 按情绪分排序，取前5
        stock_list.sort(key=lambda x: x['score'], reverse=True)
        return stock_list[:5]
    except Exception as e:
        print(f"选股失败: {e}")
        return []


def get_sector_heat():
    """获取板块热度 - 使用Baostock行业数据"""
    try:
        lg = bs.login()
        if lg.error_code != '0':
            return []
        
        # 获取行业分类
        rs = bs.query_stock_industry()
        industries = {}
        
        while rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            industry = row[2]  # 行业名称
            code = row[1]      # 股票代码
            
            if industry not in industries:
                industries[industry] = []
            industries[industry].append(code)
        
        # 计算每个行业的平均涨幅（简化版，取前3只股票）
        today = datetime.now().strftime('%Y-%m-%d')
        sector_changes = []
        
        for industry, codes in list(industries.items())[:10]:  # 只查前10个行业
            changes = []
            for code in codes[:3]:  # 每个行业取前3只
                rs = bs.query_history_k_data_plus(code, "pctChg",
                    start_date=today, end_date=today)
                if rs.error_code == '0' and rs.next():
                    try:
                        changes.append(float(rs.get_row_data()[0]))
                    except:
                        pass
            
            if changes:
                avg_change = sum(changes) / len(changes)
                sector_changes.append({
                    'name': industry,
                    'change': avg_change
                })
        
        bs.logout()
        
        # 按涨幅排序，取前5
        sector_changes.sort(key=lambda x: x['change'], reverse=True)
        return sector_changes[:5]
    except Exception as e:
        print(f"获取板块热度失败: {e}")
        return []


def generate_report(market, stocks, sectors):
    """生成报告"""
    now = datetime.now().strftime('%m月%d日 %H:%M')
    
    # 市场概况
    market_text = ""
    for key in ['sh', 'sz', 'cy']:
        if key in market:
            m = market[key]
            emoji = "📈" if m['change'] >= 0 else "📉"
            market_text += f"{emoji} {m['name']}: {m['value']:.2f} ({m['change']:+.2f}%)\n"
    
    if not market_text:
        market_text = "暂无数据\n"
    
    # 板块热度
    sector_text = ""
    for i, s in enumerate(sectors, 1):
        emoji = "🔥" if s['change'] > 0 else "❄️"
        sector_text += f"{i}. {emoji} {s['name']}: {s['change']:+.2f}%\n"
    
    if not sector_text:
        sector_text = "暂无数据\n"
    
    # 选股TOP5
    stock_text = ""
    for i, s in enumerate(stocks, 1):
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
        signal = "🔴 BUY" if s['change'] > 5 else "🟡 WATCH" if s['change'] > 2 else "⚪ HOLD"
        
        stock_text += f"{emoji} {s['name']}({s['code']})\n"
        stock_text += f"   价格: ¥{s['price']:.2f} | 涨幅: {s['change']:+.2f}% | 换手: {s['turnover']:.1f}%\n"
        stock_text += f"   情绪分: {s['score']:.1f} | 信号: {signal}\n\n"
    
    if not stock_text:
        stock_text = "暂无数据\n"
    
    report = f"""📊 A股情绪晨间预警 | {now}

📈 市场概况
{market_text}
🔥 板块热度TOP5
{sector_text}
🎯 情绪选股TOP5
{stock_text}
⚠️ 免责声明：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。"""
    
    return report


def main():
    print("🚀 A股情绪晨间预警系统 (Baostock版)")
    print("=" * 50)
    print(f"⏰ 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 检查配置
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("❌ 未设置飞书APP ID或Secret")
        return
    
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
    print(report[:500] + "...")
    
    # 发送到飞书
    print("\n📤 正在推送到飞书...")
    success = send_feishu_message(report)
    
    if success:
        print("\n✅ 完成! 飞书消息已发送")
        # 保存报告
        filename = f'report_{datetime.now().strftime("%Y%m%d")}.md'
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"📄 报告已保存到 {filename}")
    else:
        print("\n❌ 飞书消息发送失败!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
