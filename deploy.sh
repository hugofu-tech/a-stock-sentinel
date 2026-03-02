#!/bin/bash
# 一键部署脚本

echo "🚀 A股情绪预警系统 - 一键部署"
echo "==============================="
echo ""

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

cd "$(dirname "$0")"

echo "📋 检查环境..."

# 检查git
if ! command -v git &> /dev/null; then
    echo "❌ git未安装"
    exit 1
fi
echo -e "${GREEN}✓${NC} git已安装"

# 检查GitHub CLI
if command -v gh &> /dev/null; then
    echo -e "${GREEN}✓${NC} GitHub CLI已安装"
    GH_CLI=true
else
    echo -e "${YELLOW}!${NC} GitHub CLI未安装（可选，用于自动创建仓库）"
    GH_CLI=false
fi

# 初始化git
if [ ! -d .git ]; then
    echo ""
    echo "📦 初始化git仓库..."
    git init
    git branch -M main
fi

# 添加文件
echo ""
echo "📁 添加文件..."
git add .

# 提交
echo "💾 提交更改..."
git commit -m "A股情绪预警系统 v1.0 - $(date +%Y-%m-%d)" || echo "没有新更改"

# 创建GitHub仓库
if [ "$GH_CLI" = true ]; then
    echo ""
    echo "🌐 创建GitHub仓库..."
    gh repo create a-stock-sentinel --public --source=. --remote=origin --push || {
        echo "仓库可能已存在，尝试关联..."
        git remote add origin https://github.com/$(gh api user -q '.login')/a-stock-sentinel.git 2>/dev/null || true
        git push -u origin main
    }
else
    echo ""
    echo "📋 请手动创建GitHub仓库:"
    echo "   1. 访问 https://github.com/new"
    echo "   2. 仓库名: a-stock-sentinel"
    echo "   3. 创建后运行:"
    echo "      git remote add origin https://github.com/您的用户名/a-stock-sentinel.git"
    echo "      git push -u origin main"
fi

echo ""
echo "==============================="
echo "✅ 部署完成！"
echo "==============================="
echo ""
echo "📋 下一步 - 配置Secrets:"
echo "   访问: https://github.com/$(git remote get-url origin 2>/dev/null | sed 's/.*github.com\///;s/\.git//' || echo '您的用户名')/a-stock-sentinel/settings/secrets/actions"
echo ""
echo "添加以下Secrets:"
echo "   FEISHU_APP_ID: cli_a9f70dfaa379dbd7"
echo "   FEISHU_APP_SECRET: j5MoWSysARI0tQLLfeywWfKRXEunzv7Y"
echo "   FEISHU_TARGET: user:ou_0ad234b6ebfca4f424bd582393734d0f"
echo ""
echo "🧪 手动测试:"
echo "   Actions → A股情绪晨间预警 → Run workflow"
echo ""
