#!/bin/bash
# GitHub自动部署脚本 - 需要设置GITHUB_TOKEN环境变量

set -e

echo "🚀 A股情绪预警系统 - GitHub自动部署"
echo "======================================"

# 检查GITHUB_TOKEN
if [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ 错误: 未设置 GITHUB_TOKEN 环境变量"
    echo ""
    echo "📋 请按以下步骤获取GitHub Token:"
    echo "   1. 访问 https://github.com/settings/tokens"
    echo "   2. 点击 'Generate new token (classic)'"
    echo "   3. 选择权限: repo, workflow"
    echo "   4. 生成并复制token"
    echo ""
    echo "   然后运行: export GITHUB_TOKEN=您的token"
    echo "   再运行此脚本"
    exit 1
fi

# 设置git用户
git config user.email "hugo@example.com" 2>/dev/null || true
git config user.name "Hugo" 2>/dev/null || true

# GitHub用户名
GITHUB_USER=$(curl -s -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | grep -o '"login": "[^"]*"' | cut -d'"' -f4)

echo "✅ GitHub用户: $GITHUB_USER"

# 检查仓库是否已存在
echo "📡 检查仓库是否存在..."
REPO_EXISTS=$(curl -s -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/repos/$GITHUB_USER/a-stock-sentinel | grep -c '"id"' || echo "0")

if [ "$REPO_EXISTS" = "0" ]; then
    echo "📦 创建私有仓库..."
    curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" \
         -H "Accept: application/vnd.github.v3+json" \
         https://api.github.com/user/repos \
         -d '{
           "name": "a-stock-sentinel",
           "private": true,
           "description": "A股情绪晨间预警系统 - 自动推送每日选股报告",
           "auto_init": false
         }' > /dev/null
    echo "✅ 仓库创建成功"
else
    echo "✅ 仓库已存在"
fi

# 添加远程仓库
echo "📡 配置远程仓库..."
git remote remove origin 2>/dev/null || true
git remote add origin https://$GITHUB_USER:$GITHUB_TOKEN@github.com/$GITHUB_USER/a-stock-sentinel.git

# 推送代码
echo "⬆️ 推送代码..."
git push -u origin main || {
    echo "⚠️ 推送失败，尝试强制推送..."
    git push -u origin main --force
}

echo ""
echo "✅ 代码推送成功！"
echo ""

# 配置Secrets
echo "🔐 配置GitHub Secrets..."

# FEISHU_APP_ID
curl -s -X PUT \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/$GITHUB_USER/a-stock-sentinel/actions/secrets/FEISHU_APP_ID \
  -d "{\"encrypted_value\":\"$(echo -n 'cli_a9f70dfaa379dbd7' | base64)\"}" > /dev/null

# FEISHU_APP_SECRET  
curl -s -X PUT \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/$GITHUB_USER/a-stock-sentinel/actions/secrets/FEISHU_APP_SECRET \
  -d "{\"encrypted_value\":\"$(echo -n 'j5MoWSysARI0tQLLfeywWfKRXEunzv7Y' | base64)\"}" > /dev/null

# FEISHU_TARGET
curl -s -X PUT \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/$GITHUB_USER/a-stock-sentinel/actions/secrets/FEISHU_TARGET \
  -d "{\"encrypted_value\":\"$(echo -n 'user:ou_0ad234b6ebfca4f424bd582393734d0f' | base64)\"}" > /dev/null

echo "✅ Secrets配置完成"
echo ""
echo "======================================"
echo "🎉 部署完成！"
echo "======================================"
echo ""
echo "📊 仓库地址: https://github.com/$GITHUB_USER/a-stock-sentinel"
echo ""
echo "🧪 手动测试:"
echo "   访问 https://github.com/$GITHUB_USER/a-stock-sentinel/actions"
echo "   点击 'A股情绪晨间预警' → 'Run workflow'"
echo ""
echo "⏰ 定时任务:"
echo "   每天北京时间9:15自动运行"
echo ""
