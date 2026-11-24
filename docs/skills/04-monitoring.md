---
name: uptime-monitoring-feishu-alert
description: 给财务 AI 服务加监控告警：定时检查网页、飞书机器人、PostgreSQL 是否存活，异常时通过飞书自定义机器人推送到群，并附带自动恢复动作。
---

# 04 · 监控告警（健康检查 + 飞书推送）

## 目标

- 服务挂了 **5 分钟内**你就能收到飞书消息，而不是等用户来抱怨
- 能区分"网页挂了""机器人挂了""数据库挂了"
- 检查本身不会误报（连续失败才告警）

## 前置条件

- 服务器上 `finance-ai`、`finance-bot` 服务在跑
- 有一个飞书群，能添加「自定义机器人」

---

## 实施步骤

### 1. 建飞书告警群机器人

1. 飞书里建个群（比如"运维告警"，只有你自己）
2. 群设置 → **群机器人** → **添加机器人** → **自定义机器人**
3. 复制 Webhook 地址，形如：
   `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx`
4. （可选）开启"签名校验"，记下密钥

### 2. 写检查脚本 `/opt/finance-ai/healthcheck.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""健康检查：网页 / 机器人 / 数据库；异常时推飞书"""

import json
import os
import subprocess
from datetime import datetime

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

WEBHOOK = os.environ.get("ALERT_WEBHOOK", "").strip()
STATE_FILE = os.path.join(BASE_DIR, ".health_state.json")
FAIL_THRESHOLD = 2   # 连续失败 2 次才告警，避免抖动误报


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def check_web():
    try:
        r = requests.get("http://127.0.0.1:8501/_stcore/health", timeout=8)
        return r.status_code == 200, f"HTTP {r.status_code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def check_bot():
    ok, out = sh("systemctl is-active finance-bot")
    return (out == "active"), f"systemd={out}"


def check_db():
    ok, out = sh(
        "PGPASSWORD=$(grep '^PGPASSWORD=' %s/.env | cut -d= -f2 | tr -d '\\r') "
        "psql -h 127.0.0.1 -U finance -d finance -tAc 'SELECT 1'" % BASE_DIR
    )
    return (ok and out.strip() == "1"), f"psql={out[:60]}"


def send_feishu(text):
    if not WEBHOOK:
        print("[警告] 未配置 ALERT_WEBHOOK，跳过推送")
        return
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        requests.post(WEBHOOK, json=payload, timeout=10)
    except Exception as exc:
        print("推送失败:", exc)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def main():
    checks = {"网页": check_web(), "飞书机器人": check_bot(), "数据库": check_db()}
    state = load_state()
    lines = []
    alerts = []
    footer = []

    for name, (ok, detail) in checks.items():
        if ok:
            state[name] = 0
            lines.append(f"✅ {name}: 正常")
        else:
            state[name] = state.get(name, 0) + 1
            lines.append(f"❌ {name}: 失败（连续 {state[name]} 次）— {detail}")
            if state[name] == FAIL_THRESHOLD:
                alerts.append(f"❌ {name} 异常：{detail}")
                footer.append(name)

    save_state(state)

    if alerts:
        msg = (
            "🚨 财务系统告警 "
            + datetime.now().strftime("%m-%d %H:%M")
            + "\n" + "\n".join(alerts)
            + "\n\n可尝试：systemctl restart finance-ai finance-bot"
        )
        send_feishu(msg)
        print(msg)

        # 自动恢复（可选，默认关闭；把 AUTO_RESTART=1 写进 .env 开启）
        if os.environ.get("AUTO_RESTART") == "1":
            for name in footer:
                if name == "网页":
                    sh("systemctl restart finance-ai")
                elif name == "飞书机器人":
                    sh("systemctl restart finance-bot")
            send_feishu("🔧 已尝试自动重启：" + "、".join(footer))
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
```

写进 `.env`：

```env
ALERT_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/你的地址
AUTO_RESTART=1
```

### 3. systemd 定时器

`/etc/systemd/system/finance-healthcheck.service`：

```ini
[Unit]
Description=Finance system healthcheck
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/opt/finance-ai
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=-/opt/finance-ai/.env
ExecStart=/opt/finance-ai/.venv/bin/python /opt/finance-ai/healthcheck.py
```

`/etc/systemd/system/finance-healthcheck.timer`：

```ini
[Unit]
Description=Run finance healthcheck every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now finance-healthcheck.timer
systemctl list-timers | grep finance
```

### 4. 手动测一次

```bash
cd /opt/finance-ai && .venv/bin/python healthcheck.py
```

临时把服务停掉验证告警（手动触发两次，因为阈值是 2）：

```bash
systemctl stop finance-bot
for i in 1 2; do .venv/bin/python /opt/finance-ai/healthcheck.py; sleep 1; done
systemctl start finance-bot
```

---

## 验收标准

- [ ] 正常时执行输出三个 ✅，飞书无消息
- [ ] 停掉 `finance-bot` 后连续跑两次，飞书群收到告警
- [ ] 恢复服务后再跑一次，状态归零、不再重复告警
- [ ] `systemctl list-timers` 能看到 5 分钟周期

## 常见坑

| 坑 | 说明 |
|---|---|
| 每次都告警 | 用 `FAIL_THRESHOLD` + 状态文件做去抖，避免网络抖动误报 |
| 告警风暴 | 只在该状态**刚达标**时推一次（代码里 `state[name] == FAIL_THRESHOLD`），持续故障不重复刷屏 |
| Webhook 泄露 | 别提交进 git；放 `.env` |
| `_stcore/health` 路径 | Streamlit 专用健康检查端点，返回 200 表示服务活着 |
| 时区 | 服务器设成 `Asia/Shanghai`，否则告警时间差 8 小时 |
