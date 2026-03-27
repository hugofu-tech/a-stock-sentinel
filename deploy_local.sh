#!/bin/bash
# ============================================================
# Trump Sentinel - Mac mini 本地部署脚本
# ============================================================
# 使用方法：
#   chmod +x deploy_local.sh
#   ./deploy_local.sh          # 安装依赖
#   ./deploy_local.sh run      # 启动持续监控
#   ./deploy_local.sh test     # 单次dry-run测试
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[部署]${NC} $1"; }
warn() { echo -e "${YELLOW}[警告]${NC} $1"; }
err() { echo -e "${RED}[错误]${NC} $1"; }

# ============================================================
# 安装依赖
# ============================================================
install_deps() {
    log "安装Python依赖..."
    pip3 install -q requests beautifulsoup4 openai playwright

    log "安装Playwright浏览器（Chromium）..."
    python3 -m playwright install chromium
    python3 -m playwright install-deps chromium 2>/dev/null || true

    log "依赖安装完成！"
}

# ============================================================
# 验证配置
# ============================================================
check_config() {
    log "验证配置..."

    python3 -c "
from trump_config import *
issues = []

if not KIMI_API_KEY:
    issues.append('KIMI_API_KEY 未配置')
if not SMTP_USER:
    issues.append('SMTP_USER 未配置')
if not SMTP_PASSWORD:
    issues.append('SMTP_PASSWORD 未配置')
if not EMAIL_RECIPIENTS or not EMAIL_RECIPIENTS[0]:
    issues.append('EMAIL_RECIPIENTS 未配置')

# 测试Playwright
try:
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True, args=['--no-sandbox'])
    b.close()
    pw.stop()
    print('  Playwright: OK')
except Exception as e:
    issues.append(f'Playwright不可用: {e}')

print(f'  Kimi API: {\"OK\" if KIMI_API_KEY else \"未配置\"}')
print(f'  邮箱: {SMTP_USER} -> {\", \".join(EMAIL_RECIPIENTS)}')
print(f'  Twitter API: {\"OK\" if TWITTER_BEARER_TOKEN else \"未配置（可选）\"}')

if issues:
    print(f'\\n  问题: {\"; \".join(issues)}')
else:
    print('\\n  全部配置正常！')
"
}

# ============================================================
# 主逻辑
# ============================================================
case "${1:-install}" in
    install)
        log "=== Trump Sentinel 本地部署 ==="
        install_deps
        check_config
        log "部署完成！运行 ./deploy_local.sh run 启动监控"
        ;;
    run)
        log "=== 启动持续监控 ==="
        check_config
        echo ""
        log "启动中... (Ctrl+C停止)"
        python3 trump_sentinel.py --loop --interval 30
        ;;
    test)
        log "=== 单次测试运行 ==="
        python3 trump_sentinel.py --dry-run
        ;;
    check)
        check_config
        ;;
    *)
        echo "用法: $0 {install|run|test|check}"
        exit 1
        ;;
esac
