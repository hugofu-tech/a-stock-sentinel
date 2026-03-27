"""浏览器自动化登录 — 获取雪球/微博的认证Cookie

使用Playwright无头浏览器自动登录，获取Cookie后供爬虫使用。
仅在腾讯云服务器上运行（需要安装Playwright）。

安装: pip install playwright && playwright install chromium
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

COOKIE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cookies")


def _ensure_cookie_dir():
    os.makedirs(COOKIE_DIR, exist_ok=True)


def _cookie_file(platform: str) -> str:
    _ensure_cookie_dir()
    return os.path.join(COOKIE_DIR, f"{platform}_cookies.json")


def _save_cookies(platform: str, cookies: list):
    with open(_cookie_file(platform), 'w') as f:
        json.dump({
            'cookies': cookies,
            'saved_at': datetime.now().isoformat(),
        }, f, ensure_ascii=False)
    logger.info(f"[BrowserAuth] {platform} cookies已保存 ({len(cookies)}个)")


def load_cookies(platform: str) -> Optional[list]:
    """加载已保存的cookies"""
    path = _cookie_file(platform)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        saved_at = data.get('saved_at', '')
        cookies = data.get('cookies', [])
        if cookies:
            logger.info(f"[BrowserAuth] 加载 {platform} cookies ({len(cookies)}个, 保存于{saved_at})")
            return cookies
    except Exception as e:
        logger.warning(f"[BrowserAuth] 加载 {platform} cookies失败: {e}")
    return None


def cookies_to_dict(cookies: list) -> Dict[str, str]:
    """将cookie列表转为dict（供requests.Session使用）"""
    return {c['name']: c['value'] for c in cookies if 'name' in c and 'value' in c}


def login_xueqiu(username: str = "", password: str = "") -> Optional[list]:
    """使用Playwright登录雪球，获取认证Cookie

    Args:
        username: 雪球账号（手机号或邮箱）
        password: 密码
    Returns:
        cookie列表，失败返回None
    """
    username = username or os.getenv("XUEQIU_USERNAME", "")
    password = password or os.getenv("XUEQIU_PASSWORD", "")

    if not username or not password:
        logger.warning("[BrowserAuth] 雪球用户名或密码未配置")
        return None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("[BrowserAuth] playwright未安装，请执行: pip install playwright && playwright install chromium")
        return None

    logger.info("[BrowserAuth] 开始雪球登录...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # 访问雪球首页
            page.goto("https://xueqiu.com", timeout=30000)
            time.sleep(2)

            # 点击登录按钮
            try:
                page.click('a[href*="login"]', timeout=5000)
            except:
                # 可能已经在登录页
                pass
            time.sleep(1)

            # 尝试找到登录表单
            # 雪球登录页面可能有多种布局
            try:
                # 手机号登录
                phone_input = page.query_selector('input[name="phone"]') or \
                              page.query_selector('input[placeholder*="手机"]') or \
                              page.query_selector('input[type="tel"]')
                if phone_input:
                    phone_input.fill(username)

                pwd_input = page.query_selector('input[name="password"]') or \
                            page.query_selector('input[type="password"]')
                if pwd_input:
                    pwd_input.fill(password)

                # 点击登录
                submit = page.query_selector('button[type="submit"]') or \
                         page.query_selector('button:has-text("登录")')
                if submit:
                    submit.click()
                    time.sleep(5)  # 等待登录完成

            except Exception as e:
                logger.warning(f"[BrowserAuth] 雪球登录表单交互失败: {e}")

            # 无论登录是否成功，获取cookies
            cookies = context.cookies()
            browser.close()

            if cookies:
                # 检查是否有关键cookie
                cookie_names = [c['name'] for c in cookies]
                if 'xq_a_token' in cookie_names or 'u' in cookie_names:
                    _save_cookies('xueqiu', cookies)
                    logger.info("[BrowserAuth] 雪球登录成功")
                    return cookies
                else:
                    # 即使没有token，也保存（可能是游客cookie）
                    _save_cookies('xueqiu', cookies)
                    logger.warning("[BrowserAuth] 雪球登录可能未成功，保存游客cookies")
                    return cookies

    except Exception as e:
        logger.error(f"[BrowserAuth] 雪球登录异常: {e}")

    return None


def login_weibo(username: str = "", password: str = "") -> Optional[list]:
    """使用Playwright登录微博，获取认证Cookie

    Args:
        username: 微博账号（手机号或邮箱）
        password: 密码
    Returns:
        cookie列表，失败返回None
    """
    username = username or os.getenv("WEIBO_USERNAME", "")
    password = password or os.getenv("WEIBO_PASSWORD", "")

    if not username or not password:
        logger.warning("[BrowserAuth] 微博用户名或密码未配置")
        return None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("[BrowserAuth] playwright未安装")
        return None

    logger.info("[BrowserAuth] 开始微博登录...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # 访问微博移动版登录页
            page.goto("https://passport.weibo.com/sso/signin", timeout=30000)
            time.sleep(3)

            try:
                # 输入账号
                username_input = page.query_selector('input[name="username"]') or \
                                 page.query_selector('input[id="loginName"]') or \
                                 page.query_selector('input[placeholder*="邮箱"]') or \
                                 page.query_selector('input[placeholder*="手机"]')
                if username_input:
                    username_input.fill(username)

                # 输入密码
                pwd_input = page.query_selector('input[name="password"]') or \
                            page.query_selector('input[id="loginPassword"]') or \
                            page.query_selector('input[type="password"]')
                if pwd_input:
                    pwd_input.fill(password)

                time.sleep(1)

                # 点击登录
                submit = page.query_selector('button[type="submit"]') or \
                         page.query_selector('a[node-type="submitBtn"]') or \
                         page.query_selector('button:has-text("登录")')
                if submit:
                    submit.click()
                    time.sleep(5)

            except Exception as e:
                logger.warning(f"[BrowserAuth] 微博登录表单交互失败: {e}")

            # 获取cookies
            cookies = context.cookies()
            browser.close()

            if cookies:
                cookie_names = [c['name'] for c in cookies]
                if 'SUB' in cookie_names or 'SUBP' in cookie_names:
                    _save_cookies('weibo', cookies)
                    logger.info("[BrowserAuth] 微博登录成功")
                    return cookies
                else:
                    _save_cookies('weibo', cookies)
                    logger.warning("[BrowserAuth] 微博登录可能未成功，保存当前cookies")
                    return cookies

    except Exception as e:
        logger.error(f"[BrowserAuth] 微博登录异常: {e}")

    return None


def refresh_all_cookies():
    """刷新所有平台的cookies（供定时任务调用）"""
    results = {}

    xq = login_xueqiu()
    results['xueqiu'] = len(xq) if xq else 0

    wb = login_weibo()
    results['weibo'] = len(wb) if wb else 0

    logger.info(f"[BrowserAuth] Cookie刷新完成: {results}")
    return results


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print("=== 浏览器登录Cookie获取 ===")
    print("需要先安装: pip install playwright && playwright install chromium")
    print()

    import sys
    if len(sys.argv) > 1:
        platform = sys.argv[1]
        if platform == 'xueqiu':
            login_xueqiu()
        elif platform == 'weibo':
            login_weibo()
        elif platform == 'all':
            refresh_all_cookies()
    else:
        refresh_all_cookies()
