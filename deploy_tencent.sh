#!/bin/bash
# A股情绪选股系统 — 腾讯云一键部署脚本
# 用法: bash deploy.sh

set -e

echo "=========================================="
echo "  A股情绪选股系统 — 一键部署"
echo "=========================================="

# 1. 系统更新 + 基础工具
echo "[1/7] 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git cron > /dev/null 2>&1
echo "  系统依赖安装完成"

# 2. 克隆代码
echo "[2/7] 克隆项目代码..."
PROJECT_DIR="/opt/a-stock-sentinel"
if [ -d "$PROJECT_DIR" ]; then
    echo "  项目目录已存在，拉取最新代码..."
    cd "$PROJECT_DIR"
    git fetch origin
    git checkout claude/review-project-history-DkFKw
    git pull origin claude/review-project-history-DkFKw
else
    git clone -b claude/review-project-history-DkFKw \
        https://github.com/hugofu-tech/a-stock-sentinel.git "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi
echo "  代码就绪: $PROJECT_DIR"

# 3. Python虚拟环境
echo "[3/7] 创建Python虚拟环境..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
echo "  虚拟环境创建完成"

# 4. 安装依赖
echo "[4/7] 安装Python依赖..."
pip install -r requirements.txt -q
pip install openai httpx -q
echo "  依赖安装完成"

# 5. 创建数据目录和日志目录
echo "[5/7] 创建数据和日志目录..."
mkdir -p data logs
echo "  目录创建完成"

# 6. 配置环境变量
echo "[6/7] 配置环境变量..."
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'ENVEOF'
# Kimi K2.5 API (Coding Plan)
LLM_API_KEY=sk-kimi-e54HLtfDf4T0Mei4nxcZt7l14vQMG9QigQPaeL1vmjdyTc5GT3wMXwOqsEaKISGk

# 飞书配置（如有）
FEISHU_WEBHOOK_URL=
FEISHU_APP_ID=
FEISHU_APP_SECRET=

# QQ邮箱配置（待老板提供）
EMAIL_SENDER=
EMAIL_PASSWORD=
EMAIL_RECEIVERS=

# 日志级别
LOG_LEVEL=INFO
ENVEOF
    echo "  环境变量文件创建: $ENV_FILE"
    echo "  请稍后编辑 $ENV_FILE 填入实际密钥"
else
    echo "  环境变量文件已存在，跳过"
fi

# 7. 创建启动脚本
echo "[7/7] 创建启动脚本和定时任务..."

# 夜间管线脚本
cat > "$PROJECT_DIR/run_nightly.sh" << 'SCRIPT'
#!/bin/bash
cd /opt/a-stock-sentinel
source venv/bin/activate
set -a; source .env; set +a
python scheduler.py nightly >> logs/nightly.log 2>&1
SCRIPT
chmod +x "$PROJECT_DIR/run_nightly.sh"

# 晨间管线脚本
cat > "$PROJECT_DIR/run_morning.sh" << 'SCRIPT'
#!/bin/bash
cd /opt/a-stock-sentinel
source venv/bin/activate
set -a; source .env; set +a
python scheduler.py morning >> logs/morning.log 2>&1
SCRIPT
chmod +x "$PROJECT_DIR/run_morning.sh"

# 设置crontab
(crontab -l 2>/dev/null | grep -v "a-stock-sentinel"; echo "# A股情绪选股系统
0 22 * * 1-5 /opt/a-stock-sentinel/run_nightly.sh
30 8 * * 1-5 /opt/a-stock-sentinel/run_morning.sh") | crontab -
echo "  定时任务已设置: 周一至周五 22:00夜间采集, 08:30晨间推荐"

# 8. 验证
echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "项目目录: $PROJECT_DIR"
echo "环境变量: $PROJECT_DIR/.env"
echo "日志目录: $PROJECT_DIR/logs/"
echo ""
echo "定时任务:"
echo "  22:00 周一-周五 → 夜间管线（社交媒体采集+NLP分析）"
echo "  08:30 周一-周五 → 晨间管线（评分+推荐+通知）"
echo ""
echo "手动测试:"
echo "  cd $PROJECT_DIR && source venv/bin/activate"
echo "  set -a; source .env; set +a"
echo "  python scheduler.py full    # 运行完整流水线"
echo "  python scheduler.py nightly # 仅夜间管线"
echo "  python scheduler.py morning # 仅晨间管线"
echo ""
echo "查看日志:"
echo "  tail -f logs/nightly.log"
echo "  tail -f logs/morning.log"
echo ""
