---
name: cda-quiz-game
description: 生成与维护「CDA 数据分析师闯关答题」产品。提供两种形态：① 单文件离线版（双击即玩）② SaaS 联网版（账号体系 / 服务端判分 / 排行榜 / 题库后台 / Docker 一键部署）。内置 SVG 动态卡通角色、Web Audio 实时合成音效、连击奖励语音、彩带粒子与错题复盘。做答题闯关、游戏化学习、培训考核系统时使用本 Skill。
---

# CDA 数据分析师 · 闯关答题 Skill

同一套玩法内核，两种交付形态。

| | 单文件版 | SaaS 版 |
| --- | --- | --- |
| 入口 | `CDA数据分析师闯关大冒险.html` | `cda-saas/` 项目 |
| 运行 | 双击浏览器打开 | `node server/index.mjs` 或 Docker |
| 依赖 | 无 | 无（Node 24 内置模块，零 npm 包） |
| 账号 | 无 | 注册/登录、角色权限、会话 Cookie |
| 判分 | 前端 | **服务端**（答案不下发，防作弊） |
| 数据 | localStorage 徽章 | SQLite 全量入库 |
| 榜单 | 无 | 全站榜 + 分关榜 + 个人战绩 |
| 题库 | 改 HTML 数组 | 后台增删改查 |
| 部署 | 拷文件 | `bash deploy.sh 域名` → HTTPS |

---

## 一、SaaS 版（推荐用于培训 / 考核）

### 技术选型

- **运行时**：Node.js ≥ 22.5（用 `node:sqlite`，因此**不需要任何第三方依赖**）
- **后端**：`node:http` 手写路由，无 Express
- **数据库**：SQLite（WAL 模式），单文件，天然支持热备
- **前端**：原生 ES Module + CSS，无框架、无打包
- **反代**：Nginx（证书 / 压缩 / 静态缓存）
- **部署**：Docker + docker-compose，或 systemd

### 目录

```
cda-saas/
├─ server/{index,api,db,auth,env,seed-data}.mjs
├─ public/{index,admin}.html + css/ + js/{game,admin,api,sound,mascot,fx}.js
├─ test/{api-test,e2e-test}.mjs
├─ nginx/{cda,cda-http}.conf
├─ Dockerfile · docker-compose.yml · deploy.sh · README.md
```

### 数据模型

```
users(id, username, display_name, pass_hash, salt, role, created_at, last_login_at)
sessions(token, user_id, expires_at)
levels(id, name, icon, descr, sort)
questions(id, level_id, tag, q, options(json), answer, explain, sort, active)
runs(id, user_id, mode, level_id, question_ids, idx, score, combo, max_combo,
     hearts, correct_count, total_count, accuracy, stars, status, started_at, finished_at)
run_answers(id, run_id, question_id, chosen, is_correct, ms, answered_at)
```

### 关键机制

1. **服务端判分**：`POST /api/runs` 只返回题干与选项；选项提交后由服务端比对 `questions.answer`，并回传 `correct / correctIndex / explain`。前端拿不到答案。
2. **局内状态落库**：`runs.idx` 记录进度，重复提交同一题会被拒绝（409/400），刷新可续答。
3. **计分**：`100 + round(剩余秒数×4) + (连击-1)×25`，星级按正确率 90/70/50 分档。
4. **会话**：scrypt 加盐哈希；Token 32 字节随机；Cookie `HttpOnly + SameSite=Lax`；`X-Forwarded-Proto=https` 时自动加 `Secure`。
5. **权限**：`player` / `admin`；所有 `/api/admin/*` 二次校验角色；题目软删除（`active=0`）。
6. **限流**：登录 12 次/分/IP，注册 8 次/分/IP（内存桶）。

### 部署（云服务器）

```bash
# 服务器上
tar xzf cda-saas.tgz && cd cda-saas
sudo bash deploy.sh quiz.example.com
```

脚本依次完成：装 Docker → 生成 `.env`（随机管理员密码）→ `chown 1000:1000 data` → 构建启动 → 健康检查 → 装 Nginx 反代 80/443 → certbot 签发 HTTPS → ufw 放行。

⚠️ 手动部署时必须先 `mkdir -p data && chown -R 1000:1000 data`，否则容器内非 root 用户写不了 SQLite。

### 测试

```bash
node test/api-test.mjs    # 56 项后端断言
node test/e2e-test.mjs    # 31 项真浏览器端到端（需本机 Chrome）
```

E2E 覆盖：注册 → 闯关 → 服务端判分 → 结算 → 排行榜 → 个人战绩 → 越权拦截 → 管理员后台 → 题库 CRUD → 用户管理 → 移动端 → 零控制台报错。

---

## 二、单文件版（离线演示 / 活动页）

`CDA数据分析师闯关大冒险.html` —— 约 1500 行，双击即玩，无需服务器。

### 动态卡通角色
- **数小喵**：纯 SVG 手绘（猫耳、天线、腮红、帽子）。
- 5 套状态机：`is-idle`（呼吸+眨眼）/ `is-thinking`（摇摆）/ `is-happy`（弯眼跳跃）/ `is-sad`（皱眉掉泪+抖动）/ `is-win`（戴学士帽掉落）。
- **啦啦队三人组**：猫咪 / 猫头鹰 / 熊猫，答对依次起跳，答错垂头。

### 音效（Web Audio 合成，无音频文件）

| 方法 | 音色 |
| --- | --- |
| `click()` | 520–560Hz 三角波短点 |
| `correct()` | 784→1175→1568Hz 上升三和弦 |
| `wrong()` | 190→128Hz 锯齿下滑 |
| `combo(n)` | 随连击升调琶音 |
| `tick()` | 最后 5 秒读秒 |
| `level()` / `fail()` | 号角 / 叹息 |

### 奖励话语
- 答对 8 句随机夸奖 + 语音朗读（Web Speech `zh-CN`）
- 2/3/5/8 连击全屏渐变大字 + 多段彩带 + 专属播报
- 答错 5 句鼓励，不打击，只引导看解析
- 每题答后展开考点详解；结算页错题复盘 + 错题重练

### 玩法
5 关 × 5 题；单关 3 心 / 全程 5 心；30 秒倒计时；星级评定；徽章 localStorage 持久化；键盘 `1-4` 选择、`Enter` 下一题；移动端振动反馈。

---

## 三、题库维护

两版共用同一份题目结构：

```js
{ tag:"考点", q:"题干", options:["A","B","C","D"], answer:0, explain:"解析" }
```

- 单文件版：改 HTML 里的 `LEVELS` 数组。
- SaaS 版：登录后台 `/admin` → 题库管理 → 新增/编辑/删除，即时生效（无需重启）。
- 5 个关卡覆盖：业务指标 / 描述统计与假设检验 / SQL 与数据清洗 / Pandas 数据探索 / 机器学习与模型评估。

---

## 四、二次开发提示

- **换配色**：改 `:root` 的 `--accent / --accent-2 / --gold / --green / --red`。
- **换角色**：`mascotMarkup()` 返回 SVG 字符串，状态靠根节点 class；新增状态需补 `.is-xxx` 样式。
- **加音效**：`Sound.tone(freq, dur, type, vol, delay, glideTo)` 一个函数够用。
- **改文案**：`PRAISE / PRAISE_SPEAK / COMBO_WORDS / CONSOLE_WORDS / CLEAR_WORDS`。
- **换数据库**：SaaS 版所有 SQL 集中在 `server/db.mjs`，换 Postgres 只改这一层，接口层不动。
- **接企业登录**：`server/auth.mjs` 的 `createSession(userId)` 是唯一入口，OAuth 回调换 session 即可。
