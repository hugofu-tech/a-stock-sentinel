#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股情绪晨间预警 - GitHub Actions版
使用飞书应用API直接推送消息到老板
"""

import os
import json
import requests
from datetime import datetime
import akshare as ak


# 飞书配置（从GitHub Secrets读取）
FEISHU_APP_ID = os.getenv('FEISHU_APP_ID')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET')
FEISHU_TARGET = os.getenv('FEISHU_TARGET', 'user:ou_0ad234b6ebfca4f424bd582393734d0f')


def get_feishu_token():
    """获取飞书access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    data = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
    
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
    
    # 解析target
    if FEISHU_TARGET.startswith('user:'):
        receive_id_type = 'open_id'
        receive_id = FEISHU_TARGET.replace('user:', '')
    elif FEISHU_TARGET.startswith('chat:'):
        receive_id_type = 'chat_id'
        receive_id = FEISHU_TARGET.replace('chat:', '')
    else:
        receive_id_type = 'open_id'
        receive_id = FEISHU_TARGET
    
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = {"receive_id_type": receive_id_type}
    
    # 构建消息内容
    if msg_type == "text":
        message_content = json.dumps({"text": content})
    else:
        message_content = content
    
    data = {
        "receive_id": receive_id,
        "msg_type": msg_type,
        "content": message_content
    }
    
    try:
        resp = requests.post(url, json=data, headers=headers, params=params, timeout=30)
        result = resp.json()
        if result.get('code') == 0:
            print(f"✅ 飞书消息发送成功 (msg_id: {result.get('data', {}).get('message_id', 'unknown')})")
            return True
        else:
            print(f"❌ 发送失败: {result.get('msg', result)}")
            return False
    except Exception as e:
        print(f"❌ 发送异常: {e}")
        return False


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
        df = df[~df['名称'].str.contains('ST', na=False)]
        df = df[df['最新价'] < 100]
        df = df[df['涨跌幅'] < 15]
        df = df[df['成交额'] > 50000000]
        
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
                'amount': row['成交额'] / 100000000,
                'score': round(row['情绪分'], 2)
            })
        
        return results
    except Exception as e:
        print(f"选股失败: {e}")
        return []


def get_sector_heat():
    """获取板块热度"""
    try:
        df = ak.stock_board_industry_name_em()
        sectors = []
        for _, row in df.head(5).iterrows():
            sectors.append({
                'name': row['板块名称'],
                'change': float(row['涨跌幅'])
            })
        return sectors
    except Exception as e:
        print(f"获取板块热度失败: {e}")
        return []


def generate_report(market, stocks, sectors):
    """生成报告"""
    now = datetime.now().strftime('%m月%d日 %H:%M')
    
    market_text = ""
    for key in ['sh', 'sz', 'cy']:
        if key in market:
            m = market[key]
            emoji = "📈" if m['change'] >= 0 else "📉"
            market_text += f"{emoji} {m['name']}: {m['value']:.2f} ({m['change']:+.2f}%)\n"
    
    sector_text = ""
    for i, s in enumerate(sectors, 1):
        sector_text += f"{i}. {s['name']}: {s['change']:+.2f}%\n"
    
    stock_text = ""
    for i, s in enumerate(stocks, 1):
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
        if s['change'] > 5:
            hold = "1-2天"
        elif s['change'] > 2:
            hold = "2-3天"
        else:
            hold = "3-5天"
        
        stock_text += f"{emoji} {s['name']}({s['code']})\n"
        stock_text += f"   价格: ¥{s['price']:.2f} 涨幅: {s['change']:+.2f}% 换手: {s['turnover']:.1f}%\n"
        stock_text += f"   情绪分: {s['score']:.1f} 建议持有: {hold}\n\n"
    
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
    print("🚀 A股情绪晨间预警系统")
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
    
    # 发送到飞书
    print("\n📤 正在推送到飞书...")
    success = send_feishu_message(report)
    
    if success:
        print("\n✅ 完成! 飞书消息已发送")
        # 保存报告到文件
        with open(f'report_{datetime.now().strftime("%Y%m%d")}.md', 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"📄 报告已保存到 report_{datetime.now().strftime('%Y%m%d')}.md")
    else:
        print("\n❌ 飞书消息发送失败!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
