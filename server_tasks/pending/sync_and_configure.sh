#!/bin/bash
# 同步代码 + 配置邮箱 + 验证全流程
cd /opt/a-stock-sentinel

# 1. 同步代码
git config --global http.version HTTP/1.1
git config --global http.postBuffer 524288000
git pull origin claude/review-project-history-DkFKw || echo 'git pull failed'

# 2. 安装依赖
source venv/bin/activate
pip install flask python-dotenv httpx -q

# 3. 配置邮箱
grep -q 'EMAIL_SENDER=fyf' .env 2>/dev/null || cat >> .env << 'ENVEOF'
EMAIL_SENDER=fyf1028@qq.com
EMAIL_PASSWORD=pkrbqgunhnlabhhh
EMAIL_RECEIVERS=fyf1028@126.com,jasmineyangyang@outlook.com
ENVEOF

# 4. 配置Kimi Key
grep -q 'LLM_API_KEY=sk' .env 2>/dev/null || echo 'LLM_API_KEY=sk-kimi-e54HLtfDf4T0Mei4nxcZt7l14vQMG9QigQPaeL1vmjdyTc5GT3wMXwOqsEaKISGk' >> .env

# 5. 修复import路径
sed -i 's/from data\.tencent_api/from social.tencent_api/g' scheduler.py

# 6. 加载环境变量
set -a; source .env; set +a

# 7. 测试邮件
echo '=== EMAIL TEST ==='
python3 -c "
import os
os.environ['EMAIL_SENDER']='fyf1028@qq.com'
os.environ['EMAIL_PASSWORD']='pkrbqgunhnlabhhh'
os.environ['EMAIL_RECEIVERS']='fyf1028@126.com,jasmineyangyang@outlook.com'
from notification.email_sender import EmailSender
s=EmailSender()
print(f'available:{s.available}')
if s.available:
    ok=s.send_daily_report('# 测试\n系统邮件测试成功！','2026-03-27')
    print(f'sent:{ok}')
"

echo '=== DONE ==='
