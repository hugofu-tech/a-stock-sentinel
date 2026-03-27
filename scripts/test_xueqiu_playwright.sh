#!/bin/bash
# 在腾讯云上安装Playwright并采集雪球评论（一键执行）
set -e
cd /opt/a-stock-sentinel
source venv/bin/activate

echo "=== 1. 安装Playwright ==="
pip install playwright -q
playwright install chromium --with-deps 2>&1 | tail -5
echo "Playwright安装完成"

echo ""
echo "=== 2. 采集雪球评论（网宿科技 SZ300017）==="
python3 << 'PYEOF'
import json, time, logging, sys
logging.basicConfig(level=logging.INFO, format='%(message)s')

from playwright.sync_api import sync_playwright

def fetch_xueqiu_comments(symbol="SZ300017", max_pages=3):
    """用Playwright无头浏览器访问雪球股票页，提取评论"""
    posts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        url = f"https://xueqiu.com/S/{symbol}"
        print(f"访问: {url}")
        page.goto(url, timeout=30000, wait_until="networkidle")
        time.sleep(3)

        # 检查是否成功加载
        title = page.title()
        print(f"页面标题: {title}")

        # 获取cookie（后续API调用用）
        cookies = context.cookies()
        cookie_names = [c['name'] for c in cookies]
        print(f"Cookies: {cookie_names}")
        has_token = 'xq_a_token' in cookie_names
        print(f"有xq_a_token: {has_token}")

        if has_token:
            # 用cookie调用API获取帖子
            token = next(c['value'] for c in cookies if c['name'] == 'xq_a_token')

            import requests
            session = requests.Session()
            for c in cookies:
                session.cookies.set(c['name'], c['value'])
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
                'Referer': f'https://xueqiu.com/S/{symbol}',
            })

            # 获取帖子
            api_url = f"https://xueqiu.com/statuses/stock_timeline.json?symbol_id={symbol}&count=20&source=all"
            resp = session.get(api_url, timeout=15, verify=False)
            print(f"API Status: {resp.status_code}")

            if resp.status_code == 200:
                data = resp.json()
                items = data.get('list', data.get('statuses', []))
                for item in items:
                    posts.append({
                        'title': item.get('title', '') or item.get('text', '')[:100],
                        'text': item.get('text', ''),
                        'user': item.get('user', {}).get('screen_name', ''),
                        'created_at': item.get('created_at', ''),
                        'retweet_count': item.get('retweet_count', 0),
                        'reply_count': item.get('reply_count', 0),
                        'like_count': item.get('like_count', 0),
                    })
                print(f"API获取: {len(posts)}条帖子")

        if not posts:
            # 回退：直接从页面HTML提取
            print("API失败，尝试从HTML提取...")
            elements = page.query_selector_all('[class*="timeline"] [class*="content"]')
            if not elements:
                elements = page.query_selector_all('.stock__timeline .timeline__item')
            if not elements:
                elements = page.query_selector_all('article, .status-content, .post-content')

            for el in elements[:20]:
                text = el.inner_text().strip()
                if text and len(text) > 5:
                    posts.append({'title': text[:100], 'text': text})
            print(f"HTML提取: {len(posts)}条")

        # 保存cookies供后续使用
        with open('data/cookies/xueqiu_cookies.json', 'w') as f:
            json.dump({'cookies': cookies}, f)
        print("Cookies已保存")

        browser.close()

    return posts

import os
os.makedirs('data/cookies', exist_ok=True)

posts = fetch_xueqiu_comments("SZ300017")
print(f"\n=== 采集结果: {len(posts)}条 ===")
for i, p in enumerate(posts[:5]):
    title = p.get('title', '')[:60]
    user = p.get('user', 'unknown')
    print(f"  {i+1}. [{user}] {title}")

# 保存结果
with open('/tmp/xueqiu_test.json', 'w') as f:
    json.dump(posts, f, ensure_ascii=False, indent=2)
print(f"\n结果已保存到 /tmp/xueqiu_test.json")
PYEOF

echo ""
echo "=== 完成 ==="
