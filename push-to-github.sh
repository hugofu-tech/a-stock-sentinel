#!/bin/bash
# GitHub部署脚本

echo "🚀 推送到GitHub"
echo "==============="

# 设置git用户信息
git config user.email "hugo@example.com"
git config user.name "Hugo"

# 添加远程仓库
echo "📡 添加远程仓库..."
git remote add origin https://github.com/hugoyfj/a-stock-sentinel.git 2>/dev/null || echo "远程仓库已存在"

# 推送
echo "⬆️ 推送到GitHub..."
git push -u origin main

echo ""
echo "✅ 完成！"
echo ""
echo "📋 下一步：配置Secrets"
echo "访问: https://github.com/hugoyfj/a-stock-sentinel/settings/secrets/actions"
echo ""
echo "添加以下3个Secrets:"
echo "  FEISHU_APP_ID: cli_a9f70dfaa379dbd7"
echo "  FEISHU_APP_SECRET: j5MoWSysARI0tQLLfeywWfKRXEunzv7Y"  
echo "  FEISHU_TARGET: user:ou_0ad234b6ebfca4f424bd582393734d0f"
