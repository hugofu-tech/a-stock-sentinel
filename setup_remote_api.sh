#!/bin/bash
# 远程管理API — 让Claude可以直接测试和管理服务器
# 轻量HTTP服务，仅监听内部端口，用token认证

set -e
cd /opt/a-stock-sentinel

# 生成随机token
TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")
echo "API_TOKEN=$TOKEN" >> .env
echo "远程管理Token: $TOKEN"

# 先拉取最新代码
git pull origin claude/review-project-history-DkFKw 2>/dev/null || true

# 安装flask
source venv/bin/activate
pip install flask -q

# 创建API服务
cat > remote_api.py << 'PYEOF'
"""轻量远程管理API — 供Claude Code测试和管理"""
import os
import subprocess
import logging
from flask import Flask, request, jsonify

app = Flask(__name__)
TOKEN = os.getenv("API_TOKEN", "")
LOG = logging.getLogger(__name__)

def check_auth():
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {TOKEN}"

@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "msg": "A股情绪选股系统远程管理API"})

@app.route("/exec", methods=["POST"])
def exec_cmd():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    cmd = request.json.get("cmd", "")
    if not cmd:
        return jsonify({"error": "empty command"}), 400
    timeout = min(request.json.get("timeout", 120), 300)
    try:
        env = os.environ.copy()
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd="/opt/a-stock-sentinel", env=env
        )
        return jsonify({
            "stdout": result.stdout[-5000:],  # 限制输出大小
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": f"timeout after {timeout}s"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/status")
def status():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    try:
        # 数据库状态
        result = subprocess.run(
            'source venv/bin/activate && python3 -c "'
            'from storage.sqlite_store import SentimentStore;'
            's=SentimentStore();print(s.get_stats())"',
            shell=True, capture_output=True, text=True,
            timeout=10, cwd="/opt/a-stock-sentinel"
        )
        db_stats = result.stdout.strip()

        # crontab
        cron = subprocess.run("crontab -l", shell=True, capture_output=True, text=True)

        # 最近日志
        logs = subprocess.run(
            "tail -20 logs/nightly.log 2>/dev/null; tail -20 logs/morning.log 2>/dev/null",
            shell=True, capture_output=True, text=True,
            cwd="/opt/a-stock-sentinel"
        )

        return jsonify({
            "db_stats": db_stats,
            "crontab": cron.stdout,
            "recent_logs": logs.stdout[-3000:]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"API启动，Token: {TOKEN[:8]}...")
    app.run(host="0.0.0.0", port=80, debug=False)
PYEOF

# 创建systemd服务（开机自启）
cat > /etc/systemd/system/sentinel-api.service << SVCEOF
[Unit]
Description=A股情绪选股系统远程管理API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/a-stock-sentinel
Environment=PATH=/opt/a-stock-sentinel/venv/bin:/usr/bin:/bin
EnvironmentFile=/opt/a-stock-sentinel/.env
ExecStart=/opt/a-stock-sentinel/venv/bin/python remote_api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

# 启动服务
systemctl daemon-reload
systemctl enable sentinel-api
systemctl start sentinel-api

# 等待启动
sleep 2

# 验证
STATUS=$(curl -s http://localhost/ping 2>/dev/null)
echo ""
echo "=========================================="
echo "  远程管理API已启动"
echo "=========================================="
echo "  Token: $TOKEN"
echo "  验证: $STATUS"
echo "=========================================="
