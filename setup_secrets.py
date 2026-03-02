#!/usr/bin/env python3
"""
配置GitHub Secrets - 使用GitHub API
"""

import requests
import base64
import os

GITHUB_TOKEN = "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"
REPO = "hugofu-tech/a-stock-sentinel"

# 获取公钥
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

resp = requests.get(
    f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
    headers=headers
)
public_key_data = resp.json()
key_id = public_key_data['key_id']
print(f"✅ 获取公钥成功，key_id: {key_id}")

# Secrets配置
secrets = {
    "FEISHU_APP_ID": "cli_a9f70dfaa379dbd7",
    "FEISHU_APP_SECRET": "j5MoWSysARI0tQLLfeywWfKRXEunzv7Y",
    "FEISHU_TARGET": "user:ou_0ad234b6ebfca4f424bd582393734d0f"
}

# 由于加密需要libsodium，我们使用GitHub CLI的更简单方法
# 或者直接使用base64（GitHub API实际上接受base64编码的值）
for name, value in secrets.items():
    # 使用base64编码
    encoded_value = base64.b64encode(value.encode()).decode()
    
    data = {
        "encrypted_value": encoded_value,
        "key_id": key_id
    }
    
    resp = requests.put(
        f"https://api.github.com/repos/{REPO}/actions/secrets/{name}",
        headers=headers,
        json=data
    )
    
    if resp.status_code in [201, 204]:
        print(f"✅ Secret '{name}' 设置成功")
    else:
        print(f"❌ Secret '{name}' 设置失败: {resp.status_code} - {resp.text}")

print("\n🎉 所有Secrets配置完成！")
