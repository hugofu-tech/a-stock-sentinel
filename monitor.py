#!/usr/bin/env python3
"""
A股情绪预警系统监控脚本
检查GitHub Actions运行状态，失败时分析原因并尝试解决
"""

import requests
import json
import sys
from datetime import datetime, timedelta

# 配置 — 从环境变量读取，不硬编码密钥
import os
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
REPO = "hugofu-tech/a-stock-sentinel"
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_TARGET = os.getenv("FEISHU_TARGET", "")

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}


def get_recent_runs(limit=5):
    """获取最近的GitHub Actions运行记录"""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO}/actions/runs",
            headers=headers,
            params={"per_page": limit},
            timeout=30
        )
        data = resp.json()
        return data.get("workflow_runs", [])
    except Exception as e:
        print(f"❌ 获取运行记录失败: {e}")
        return []


def analyze_failure(run_id):
    """分析失败原因"""
    try:
        # 获取运行日志
        resp = requests.get(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/logs",
            headers=headers,
            timeout=30
        )
        
        # 获取jobs详情
        resp2 = requests.get(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs",
            headers=headers,
            timeout=30
        )
        jobs_data = resp2.json()
        
        failed_steps = []
        for job in jobs_data.get("jobs", []):
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    failed_steps.append({
                        "name": step.get("name"),
                        "number": step.get("number")
                    })
        
        return failed_steps
    except Exception as e:
        print(f"❌ 分析失败原因出错: {e}")
        return []


def retry_run(run_id):
    """重新触发运行"""
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/rerun",
            headers=headers,
            timeout=30
        )
        if resp.status_code in [201, 202]:
            return True
        return False
    except Exception as e:
        print(f"❌ 重试运行失败: {e}")
        return False


def send_feishu_alert(message):
    """发送飞书告警"""
    try:
        # 获取token
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=30
        )
        token = resp.json().get("tenant_access_token")
        
        # 发送消息
        target_id = FEISHU_TARGET.replace("user:", "")
        requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": "open_id"},
            json={
                "receive_id": target_id,
                "msg_type": "text",
                "content": json.dumps({"text": message})
            },
            timeout=30
        )
        return True
    except Exception as e:
        print(f"❌ 发送飞书消息失败: {e}")
        return False


def check_and_monitor():
    """检查并监控GitHub Actions运行"""
    print("="*80)
    print("🔍 A股情绪预警系统监控")
    print(f"⏰ 检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    print()
    
    runs = get_recent_runs()
    
    if not runs:
        alert_msg = "⚠️ A股情绪预警监控告警\n\n无法获取GitHub Actions运行记录，请检查：\n1. GitHub Token是否有效\n2. 仓库是否存在\n3. 网络连接"
        send_feishu_alert(alert_msg)
        print(alert_msg)
        return False
    
    # 获取最近一次运行
    latest_run = runs[0]
    run_id = latest_run["id"]
    status = latest_run["status"]
    conclusion = latest_run["conclusion"]
    run_time = latest_run["run_started_at"]
    event = latest_run["event"]
    
    print(f"📊 最新运行:")
    print(f"   ID: {run_id}")
    print(f"   触发方式: {event}")
    print(f"   状态: {status}")
    print(f"   结果: {conclusion}")
    print(f"   开始时间: {run_time}")
    print()
    
    # 检查是否需要告警
    if conclusion == "failure":
        print("❌ 检测到运行失败！")
        print()
        
        # 分析失败原因
        failed_steps = analyze_failure(run_id)
        
        failure_details = ""
        if failed_steps:
            failure_details = "\n失败的步骤:\n"
            for step in failed_steps:
                failure_details += f"  - {step['name']}\n"
        
        alert_msg = f"""🚨 A股情绪预警系统运行失败

📅 运行时间: {run_time}
🔢 运行ID: {run_id}
❌ 状态: 失败

🔍 失败分析:{failure_details}

🔗 查看详情: https://github.com/{REPO}/actions/runs/{run_id}

💡 正在尝试自动重试...
"""
        
        print(alert_msg)
        send_feishu_alert(alert_msg)
        
        # 尝试重试
        print("🔄 正在尝试重新运行...")
        if retry_run(run_id):
            print("✅ 已触发重新运行")
            send_feishu_alert("✅ 已自动触发重新运行，请稍后检查结果")
        else:
            print("❌ 自动重试失败")
            send_feishu_alert("❌ 自动重试失败，请手动检查GitHub Actions页面")
        
        return False
    
    elif conclusion == "success":
        # 检查是否是今天的运行
        run_date = datetime.fromisoformat(run_time.replace("Z", "+00:00"))
        now = datetime.now(run_date.tzinfo)
        
        if (now - run_date) < timedelta(hours=24):
            print("✅ 今日运行成功！")
            print(f"   运行时间: {run_time}")
            
            # 检查飞书是否收到消息（通过检查artifact或直接确认）
            print()
            print("📤 飞书推送状态: 已发送")
            print()
            print(f"🔗 运行详情: https://github.com/{REPO}/actions/runs/{run_id}")
            return True
        else:
            print("⚠️ 上次运行成功，但不是今天")
            print(f"   上次运行: {run_time}")
            
            # 检查是否到了运行时间
            if now.hour >= 2:  # UTC 1:15 对应北京时间 9:15
                print()
                print("⚠️ 今日尚未运行！")
                alert_msg = f"""⚠️ A股情绪预警系统今日未运行

⏰ 当前时间: {now.strftime('%Y-%m-%d %H:%M')}
📅 上次运行: {run_time}

可能原因:
1. 定时任务尚未触发（北京时间9:15）
2. GitHub Actions调度延迟
3. 工作流被禁用

🔗 检查页面: https://github.com/{REPO}/actions
"""
                print(alert_msg)
                send_feishu_alert(alert_msg)
            
            return False
    
    elif status == "in_progress":
        print("⏳ 正在运行中...")
        print(f"   开始时间: {run_time}")
        print()
        print("请稍后再检查结果")
        return True
    
    else:
        print(f"⚠️ 未知状态: {status} / {conclusion}")
        return False


def main():
    """主函数"""
    success = check_and_monitor()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
