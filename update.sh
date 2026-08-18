#!/bin/bash
# UniLodge QLD — Auto-update script (hardened)
# 1) 等待网络就绪（修复"睡眠唤醒后网络还没起来就抓取失败"）
# 2) 抓取失败自动重试 3 次（缓解 GFW 对澳洲 IP 的时断时续）
# 3) 失败如实报错（不再无条件打印 "Pushed successfully!"）
# 4) 推送前先对齐远程，避免 "fetch first" 分叉被拒

cd "/Users/lan/Projects/B/unilodge-qld" || exit 1

# ---- 加载 SSH key（用于 git push）----
eval "$(ssh-agent -s)" >/dev/null 2>&1
ssh-add ~/.ssh/id_ed25519 >/dev/null 2>&1

# ---- 1. 等待网络（最长 10 分钟）----
echo "[$(date)] update.sh 启动，等待网络就绪..."
net_ok=0
for _ in $(seq 1 20); do
    if curl -s --max-time 8 -o /dev/null "https://www.apple.com" 2>/dev/null \
       || curl -s --max-time 8 -o /dev/null "https://github.com" 2>/dev/null; then
        net_ok=1
        break
    fi
    sleep 30
done
if [ "$net_ok" -ne 1 ]; then
    echo "[$(date)] ❌ 网络 10 分钟未就绪 — 本次放弃（下次定时任务会重试）"
    exit 1
fi
echo "[$(date)] 网络已就绪"

# ---- 2. 抓取（最多 3 次，间隔 5 分钟）----
exit_code=1
attempt=1
while [ "$attempt" -le 3 ]; do
    echo "[$(date)] 抓取尝试 $attempt/3"
    python3 scraper.py
    exit_code=$?
    if [ "$exit_code" -eq 0 ]; then
        break
    fi
    echo "[$(date)] 抓取失败（exit $exit_code）"
    if [ "$attempt" -lt 3 ]; then
        echo "[$(date)] 5 分钟后重试..."
        sleep 300
    fi
    attempt=$((attempt + 1))
done

if [ "$exit_code" -ne 0 ]; then
    echo "[$(date)] ❌ 抓取连续失败 3 次 — 跳过推送"
    exit 1
fi

# ---- 3. 提交 & 推送（新数据优先，先对齐远程避免分叉）----
git add index.html previous_data.json
if git diff --staged --quiet; then
    echo "[$(date)] 数据无变化 — 无需推送"
    exit 0
fi

# 先拉取远程最新提交，把本地改动 rebase 到其之上，保证 push 是 fast-forward
if git fetch origin main 2>/dev/null; then
    git reset --soft origin/main
fi
git commit -m "Auto update $(date -u +'%Y-%m-%d %H:%M UTC')" >/dev/null 2>&1

if git push origin main 2>&1; then
    echo "[$(date)] ✅ 推送成功"
else
    echo "[$(date)] ❌ 推送失败 — 下次定时任务会重试"
    exit 1
fi
