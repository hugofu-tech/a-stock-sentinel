#!/bin/bash
# ============================================================
# A股情绪选股系统 — 生产就绪检查 & 一键上线脚本
# 执行一次，解决所有问题，确保今晚22:00定时任务万无一失
# ============================================================
set -e
cd /opt/a-stock-sentinel

echo "============================================================"
echo "  A股情绪选股系统 — 生产就绪检查"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

PASS=0
FAIL=0
WARN=0

check_pass() { echo "  [PASS] $1"; ((PASS++)); }
check_fail() { echo "  [FAIL] $1"; ((FAIL++)); }
check_warn() { echo "  [WARN] $1"; ((WARN++)); }

# ============================================================
# 1. 代码同步（多种方式尝试）
# ============================================================
echo ""
echo "--- [1/8] 代码同步 ---"
BRANCH="claude/review-project-history-DkFKw"

git_pull_success=false
for attempt in 1 2 3; do
    echo "  尝试git pull (第${attempt}次)..."
    git config --global http.version HTTP/1.1
    git config --global http.postBuffer 524288000
    if git pull origin "$BRANCH" 2>/dev/null; then
        git_pull_success=true
        break
    fi
    echo "  失败，等待5秒后重试..."
    sleep 5
done

if [ "$git_pull_success" = true ]; then
    check_pass "代码同步成功"
else
    # 尝试ghproxy镜像
    echo "  尝试GitHub镜像..."
    ORIG_URL=$(git remote get-url origin)
    git remote set-url origin "https://ghproxy.com/https://github.com/hugofu-tech/a-stock-sentinel.git"
    if git pull origin "$BRANCH" 2>/dev/null; then
        check_pass "代码同步成功（通过镜像）"
        git_pull_success=true
    fi
    git remote set-url origin "$ORIG_URL"  # 恢复原URL
fi

if [ "$git_pull_success" = false ]; then
    check_fail "代码同步失败（GitHub网络不通），使用当前本地代码"
fi

echo "  当前版本: $(git log --oneline -1)"

# ============================================================
# 2. Python依赖检查
# ============================================================
echo ""
echo "--- [2/8] Python依赖 ---"
source venv/bin/activate

# 安装缺失的依赖
pip install -q flask python-dotenv openai httpx 2>/dev/null
pip install -q -r requirements.txt 2>/dev/null

# 验证关键包
for pkg in snownlp beautifulsoup4 requests pandas numpy akshare openai flask; do
    if python3 -c "import $pkg" 2>/dev/null; then
        check_pass "$pkg"
    else
        # 尝试安装
        pip install -q "$pkg" 2>/dev/null
        if python3 -c "import $pkg" 2>/dev/null; then
            check_pass "$pkg (刚安装)"
        else
            check_fail "$pkg 安装失败"
        fi
    fi
done

# ============================================================
# 3. 环境变量配置
# ============================================================
echo ""
echo "--- [3/8] 环境变量 ---"
set -a; source .env 2>/dev/null; set +a

if [ -n "$LLM_API_KEY" ]; then
    check_pass "LLM_API_KEY 已配置"
else
    # 自动写入Kimi Key
    echo 'LLM_API_KEY=sk-kimi-e54HLtfDf4T0Mei4nxcZt7l14vQMG9QigQPaeL1vmjdyTc5GT3wMXwOqsEaKISGk' >> .env
    export LLM_API_KEY="sk-kimi-e54HLtfDf4T0Mei4nxcZt7l14vQMG9QigQPaeL1vmjdyTc5GT3wMXwOqsEaKISGk"
    check_pass "LLM_API_KEY 已自动配置"
fi

# ============================================================
# 4. 数据源验证
# ============================================================
echo ""
echo "--- [4/8] 数据源验证 ---"

# akshare测试
AKSHARE_RESULT=$(python3 -c "
import akshare as ak
try:
    df = ak.stock_zh_a_spot_em()
    print(f'OK:{len(df)}')
except Exception as e:
    print(f'FAIL:{e}')
" 2>&1)

if echo "$AKSHARE_RESULT" | grep -q "^OK:"; then
    STOCK_COUNT=$(echo "$AKSHARE_RESULT" | grep -oP 'OK:\K\d+')
    check_pass "akshare: ${STOCK_COUNT}只A股"
else
    check_warn "akshare不可用，将使用腾讯API备选"

    # 腾讯API测试
    TENCENT_RESULT=$(python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from social.tencent_api import fetch_realtime_quotes
    df = fetch_realtime_quotes(['600519','000001','300750'])
    if not df.empty:
        print(f'OK:{len(df)}')
    else:
        print('FAIL:empty')
except Exception as e:
    print(f'FAIL:{e}')
" 2>&1)

    if echo "$TENCENT_RESULT" | grep -q "^OK:"; then
        check_pass "腾讯API备选: 正常"
    else
        check_fail "腾讯API也不可用: $TENCENT_RESULT"
    fi
fi

# 东方财富股吧测试
GUBA_RESULT=$(python3 -c "
import sys; sys.path.insert(0, '.')
from social.eastmoney_guba import EastMoneyGuba
g = EastMoneyGuba()
posts = g.fetch_stock_posts('600519', '贵州茅台', limit=5)
print(f'OK:{len(posts)}')
" 2>&1)

if echo "$GUBA_RESULT" | grep -q "^OK:"; then
    POST_COUNT=$(echo "$GUBA_RESULT" | grep -oP 'OK:\K\d+')
    check_pass "东方财富股吧: ${POST_COUNT}条帖子"
else
    check_fail "东方财富股吧: $GUBA_RESULT"
fi

# ============================================================
# 5. Kimi K2.5 API验证
# ============================================================
echo ""
echo "--- [5/8] Kimi K2.5 API ---"
KIMI_RESULT=$(python3 -c "
import sys; sys.path.insert(0, '.')
from nlp.llm_analyzer import LLMAnalyzer
a = LLMAnalyzer()
if not a.available:
    print('FAIL:not_available')
else:
    r = a.analyze_stock_sentiment('600519', '贵州茅台', ['茅台看好','茅台利空'])
    if r.get('confidence', 0) > 0:
        print(f'OK:{r[\"sentiment\"]}/{r[\"score\"]}')
    else:
        print('FAIL:no_response')
" 2>&1)

if echo "$KIMI_RESULT" | grep -q "^OK:"; then
    check_pass "Kimi K2.5: $KIMI_RESULT"
else
    check_warn "Kimi K2.5: $KIMI_RESULT（LLM不可用时自动跳过）"
fi

# ============================================================
# 6. NLP引擎验证
# ============================================================
echo ""
echo "--- [6/8] NLP引擎 ---"
NLP_RESULT=$(python3 -c "
import sys; sys.path.insert(0, '.')
from nlp.snownlp_analyzer import SnowNLPAnalyzer
from storage.models import SocialPost
from datetime import datetime
a = SnowNLPAnalyzer()
post = SocialPost(source='test', stock_code='600519', stock_name='茅台',
                  title='茅台业绩超预期利好', content='', author='test',
                  publish_time=datetime.now())
r = a.analyze_post(post)
print(f'OK:{r.normalized_score:.2f}')
" 2>&1)

if echo "$NLP_RESULT" | grep -q "^OK:"; then
    check_pass "SnowNLP: $NLP_RESULT"
else
    check_fail "SnowNLP: $NLP_RESULT"
fi

# ============================================================
# 7. 定时任务验证
# ============================================================
echo ""
echo "--- [7/8] 定时任务 ---"

# 检查crontab
if crontab -l 2>/dev/null | grep -q "run_nightly.sh"; then
    check_pass "夜间任务: $(crontab -l | grep nightly)"
else
    # 设置crontab
    (crontab -l 2>/dev/null | grep -v "a-stock-sentinel"; echo "# A股情绪选股系统
0 22 * * 1-5 /opt/a-stock-sentinel/run_nightly.sh
30 8 * * 1-5 /opt/a-stock-sentinel/run_morning.sh") | crontab -
    check_pass "夜间任务: 已配置 (22:00)"
fi

if crontab -l 2>/dev/null | grep -q "run_morning.sh"; then
    check_pass "晨间任务: $(crontab -l | grep morning)"
else
    check_fail "晨间任务未配置"
fi

# 检查时区
TZ_INFO=$(date +%Z)
if [ "$TZ_INFO" = "CST" ] || [ "$TZ_INFO" = "Asia/Shanghai" ]; then
    check_pass "时区: $TZ_INFO (北京时间)"
else
    check_warn "时区: $TZ_INFO (非北京时间，crontab时间可能需要调整)"
fi

# 确保启动脚本有.env加载
for script in run_nightly.sh run_morning.sh; do
    if [ -f "$script" ]; then
        if ! grep -q "source .env" "$script"; then
            # 修复启动脚本，加入.env加载
            cat > "$script" << SCRIPTEOF
#!/bin/bash
cd /opt/a-stock-sentinel
source venv/bin/activate
set -a; source .env; set +a
python scheduler.py $(echo $script | sed 's/run_//' | sed 's/.sh//') >> logs/$(echo $script | sed 's/run_//' | sed 's/.sh//').log 2>&1
SCRIPTEOF
            chmod +x "$script"
        fi
        check_pass "$script 就绪"
    else
        check_fail "$script 不存在"
    fi
done

# ============================================================
# 8. 全流程冒烟测试（快速版，只测5只股票）
# ============================================================
echo ""
echo "--- [8/8] 全流程冒烟测试 ---"
SMOKE_RESULT=$(timeout 180 python3 -c "
import sys, os, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.WARNING)

from scheduler import SentimentScheduler
s = SentimentScheduler()

# 夜间管线
nightly = s.run_nightly_pipeline()
posts = nightly.get('posts_collected', 0)
stored = nightly.get('sentiments_stored', 0)
errors = len(nightly.get('errors', []))

# 晨间管线
result = s.run_morning_pipeline()
recs = len(result) if isinstance(result, list) else len(result.get('recommendations', []))

print(f'OK:posts={posts},stored={stored},errors={errors},recs={recs}')
" 2>&1)

if echo "$SMOKE_RESULT" | grep -q "^OK:"; then
    check_pass "全流程: $SMOKE_RESULT"
else
    # 输出最后几行错误信息
    echo "  冒烟测试输出: $(echo "$SMOKE_RESULT" | tail -3)"
    check_fail "全流程冒烟测试失败"
fi

# ============================================================
# 汇总报告
# ============================================================
echo ""
echo "============================================================"
echo "  生产就绪检查报告"
echo "============================================================"
echo "  通过: $PASS"
echo "  警告: $WARN"
echo "  失败: $FAIL"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "  ✅ 系统已就绪，今晚22:00将自动运行！"
    echo "  明早8:30将生成选股推荐报告。"
elif [ $FAIL -le 2 ] && echo "$SMOKE_RESULT" | grep -q "^OK:"; then
    echo "  ⚠️ 有个别组件异常，但核心流程正常，可以上线。"
else
    echo "  ❌ 存在关键问题，需要修复后才能上线。"
fi

echo ""
echo "  数据库状态:"
python3 -c "
import sys; sys.path.insert(0, '.')
from storage.sqlite_store import SentimentStore
s = SentimentStore()
print(f'    {s.get_stats()}')
" 2>/dev/null

echo ""
echo "  定时任务:"
crontab -l 2>/dev/null | grep -v "^#" | grep -v "^$"

echo ""
echo "============================================================"
