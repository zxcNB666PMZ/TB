# 踩坑库（35+ 条真实记录）

> 每条格式：**现象 → 根因 → 解法 → 预防**
> 全部来自一个真实上线项目（阿里云 + PostgreSQL + Streamlit + 飞书机器人 + 智谱 GLM）。

---

## 一、网络与代理

### 1. `[WinError 10054]` 远程主机强迫关闭连接
- **现象**：调用国外 API（如 Supabase）时报连接重置，浏览器能打开别的网站
- **根因**：TLS SNI 被阻断 —— TCP 能连、证书握手中断。不同域名命运不同（`*.supabase.co` 挂，`*.pooler.supabase.com` 通）
- **解法**：① 走代理；② 换可用的域名/接入点；③ 长期方案：迁到国内可用服务
- **预防**：把"国外依赖"当成风险项，架构评审时就要评估

### 2. 代理端口猜错
- **现象**：设了 `127.0.0.1:10809` 还是连不上
- **根因**：不同客户端端口不同：Clash 7890（混合）/7897（Verge）、v2rayN 10808（socks）/10809（http）
- **解法**：先 `Get-NetTCPConnection -State Listen` 看哪个端口在听，再写脚本逐个探测
- **预防**：写个 `test_proxy.py` 批量探测，别靠记忆

### 3. SOCKS 与 HTTP 代理混用
- **现象**：`requests` 报 `Missing dependencies for SOCKS support`
- **根因**：`socks5://` 需要 `pip install "requests[socks]"`
- **解法**：装 PySocks，或改用 HTTP 代理端口
- **预防**：优先用 HTTP 代理（库支持最广）

### 4. 改了系统代理想让 Python 生效
- **现象**：浏览器能通，Python 脚本不通
- **根因**：系统代理只影响部分程序；环境变量 `HTTPS_PROXY` 需在**启动进程前**设置
- **解法**：`$env:HTTPS_PROXY=...` 后再启动；或代码里显式 `proxies={...}`
- **预防**：测试脚本里把代理写死成参数，别依赖系统状态

### 5. 阿里云欠费导致"诡异断连"
- **现象**：SSH 连不上、飞书机器人无限重连（`SSLEOFError`）、但网页偶尔还能打开
- **根因**：账户余额为 0，按流量计费扣不动 → 网络被限速/限制
- **解法**：充值 → 等 2~3 分钟 → 服务自动恢复（systemd `Restart=always` 自愈）
- **预防**：预存余额；把"按流量计费"改成"固定带宽"；加余额告警

---

## 二、文件系统与编码

### 6. FAT32 U 盘写文件报 `EISDIR`
- **现象**：工具写文件时报 `illegal operation on a directory`，但文件不存在
- **根因**：写文件用了"临时文件 + 硬链接"策略，**FAT32 不支持硬链接**
- **解法**：先写到 NTFS 盘，再复制过去；或改用普通写入方式
- **预防**：**项目不要放在 U 盘/移动盘上**

### 7. U 盘当开发盘导致 git 损坏
- **现象**：`fatal: Unable to create '.git/index.lock': File exists`；切分支切一半失败
- **根因**：U 盘掉线时 git 操作中断，留下锁文件
- **解法**：`rm .git/index.lock` 后再操作
- **预防**：代码放本地硬盘，U 盘只做备份；**远程仓库才是唯一可信源**

### 8. `.env` 带 UTF-8 BOM，第一个变量永远读不到
- **现象**：智谱 Key 明明写了，程序说缺失；systemd 日志 `Ignoring invalid environment assignment 'ZHIPU_API_KEY=...'`
- **根因**：PowerShell `Set-Content -Encoding UTF8` 会写 BOM，键名变成 `\ufeffZHIPU_API_KEY`
- **解法**：`sed -i '1s/^\xEF\xBB\xBF//' .env`；或改用 `-Encoding ASCII`/无 BOM 写入
- **预防**：传输配置文件后 `head -c 3 file | xxd` 检查前 3 字节

### 9. `.env` 是 CRLF，shell 读密码带 `\r`
- **现象**：Python 里能连数据库，但 `psql` 用同样密码报认证失败
- **根因**：`grep ... | cut -d= -f2` 保留了 `\r`，密码变成 `Finance2026ok\r`
- **解法**：`| tr -d '\r'`
- **预防**：服务器上的配置文件统一 `sed -i 's/\r$//' file`

### 10. PowerShell 5.1 读写破坏 UTF-8 中文
- **现象**：`Get-Content -Raw` + `Set-Content` 后文件中文全变乱码
- **根因**：PS 5.1 的 `Get-Content` 默认按 ANSI 解码 → 再以 UTF-8 写出 = 双重编码
- **解法**：用 `Get-Content -Encoding UTF8`；或直接用写文件工具/`[IO.File]::WriteAllText`
- **预防**：**别用 shell 做文本往返修改**，用编辑器或代码

---

## 三、Python 环境

### 11. systemd 里 venv 路径差一个点
- **现象**：服务 `failed`，日志 `No such file or directory: /opt/app/venv/bin/streamlit`
- **根因**：实际目录是 `.venv`（带点）
- **解法**：`ExecStart` 写绝对路径 `/opt/app/.venv/bin/python`
- **预防**：写完 service 先手动执行一遍 `ExecStart` 命令验证

### 12. 可选依赖缺失导致整个应用崩溃
- **现象**：页面直接报 red box `ModuleNotFoundError: langchain_huggingface`
- **根因**：顶层 `import` 在 try/except 里，但 except 分支又去 import 另一个缺失包
- **解法**：用一个 `RAG_AVAILABLE` 标志包住所有相关 import，并在 UI/函数里判断
- **预防**：可选功能一律「标志位 + 降级」，不要让缺包等于全站崩

### 13. 依赖版本互相冲突
- **现象**：`ImportError: cannot import name 'eval_type_backport' from 'pydantic._internal._typing_extra'`
- **根因**：`mcp` 新版不兼容 `pydantic 2.14`
- **解法**：`pip install "pydantic>=2.7,<2.12"`
- **预防**：`requirements.txt` 钉版本；服务器装完立刻跑一次「全量 import 检查」

### 14. `python -c "import db"` 读不到 `.env`
- **现象**：`fe_sendauth: no password supplied`
- **根因**：没调 `load_dotenv()`；而且 python-dotenv 从**脚本所在目录**找 `.env`，不是当前目录
- **解法**：显式 `load_dotenv(BASE_DIR / ".env")`
- **预防**：所有需要配置的模块在 import 时先加载 env（或集中到一个 `config.py`）

### 15. 2G 内存的机器装 PyTorch
- **现象**：`pip install` 成功但运行被 OOM kill；或磁盘暴涨
- **根因**：`sentence-transformers` / `chromadb` 会拖进 PyTorch（~1.5GB 磁盘、~500MB 内存）
- **解法**：按机器内存裁剪依赖，把重功能做成可选；先加 2G swap
- **预防**：`pip install` 前先看依赖树体积（`pip download --no-deps` 或看 PyPI 大小）

---

## 四、数据库

### 16. 中文列名在 SQL 里必须加双引号
- **现象**：`syntax error at or near "价税合计"`
- **根因**：PostgreSQL 未加引号的标识符会被转小写，中文列名必须 `"价税合计"`
- **解法**：建表、查询、迁移脚本里一律加双引号
- **预防**：新项目尽量用英文列名 + 注释

### 17. 重复上传同一张发票产生脏数据
- **现象**：18 条记录实际只有 7 张不同发票
- **根因**：按"每次插入"处理，没有唯一约束
- **解法**：`"发票号码" UNIQUE` + `INSERT ... ON CONFLICT ("发票号码") DO UPDATE`
- **预防**：凡是"外部编号"字段，一律唯一约束

### 18. 去重导致迁移后数量对不上
- **现象**：源库 18 条 / 440.10 元，目标库 7 条 / 323.20 元
- **根因**：`ON CONFLICT DO NOTHING` 把重复发票号码的 11 条丢掉了
- **解法**：**先别慌，去查重复来源**（本项目：同一 PDF 上传了 6 次），确认去重是正确行为
- **预防**：迁移后必须对账：条数、金额、分布；差异必须有解释

### 19. 数据质量问题比功能缺失更致命
- **现象**：7 张发票里 4 张「销售方名称」为空，占金额 91%
- **根因**：PDF 抽取时字段缺失，没有失败重试或人工补录机制
- **解法**：① 重传原文件触发更新；② 加"抽取成功字段数"校验；③ 提供人工编辑入口
- **预防**：上线前必须抽查数据质量，不能只统计"处理了多少条"

### 20. 数据源分裂（最难查的 bug）
- **现象**：网页显示 18 条，机器人回答 7 条，用户以为系统坏了
- **根因**：网页连 Supabase，机器人连本地 SQLite
- **解法**：统一到一个库；迁移期至少要在 UI 上标注数据来源
- **预防**：**一个系统只允许一个写入源**

---

## 五、部署与打包

### 21. 服务监听 `127.0.0.1` 导致外部访问不了
- **现象**：服务器本机 `curl` 200，浏览器打不开
- **根因**：应用只绑定了回环地址
- **解法**：`--server.address 0.0.0.0`
- **预防**：部署检查清单里加一条「监听地址」

### 22. 安全组/防火墙没放行
- **现象**：`Connection timed out` / `Connection refused`
- **根因**：云平台有两套：轻量应用服务器用「防火墙」，ECS 用「安全组」
- **解法**：入方向加 TCP 业务端口；数据库端口**不要**对公网开
- **预防**：部署前先确认面板类型（轻量 vs ECS）

### 23. 用 `nohup` 起服务
- **现象**：SSH 断了服务还在，但重启服务器就没了；崩了没人拉起
- **解法**：写 systemd unit：`Restart=always` + `enable`
- **预防**：**生产环境一律 systemd / supervisor / 容器编排**

### 24. systemd 的 `EnvironmentFile` 不认带空格的配置
- **现象**：`Ignoring invalid environment assignment`
- **根因**：`.env` 里有 BOM、或值没加引号却含空格
- **解法**：清洗 `.env`；需要空格的值加双引号
- **预防**：`.env.example` 里注明格式要求

---

## 六、飞书 / 开放平台

### 25. 改了权限但没生效
- **现象**：接口一直报无权限
- **根因**：开放平台的**权限改动必须重新发布版本**才生效
- **解法**：权限管理改完 → 创建新版本 → 提交 → 管理员审核
- **预防**：把"发版本"写进接入流程的最后一步

### 26. 应用机器人 ≠ 自定义机器人
- **现象**：想在群里收告警，找不到 Webhook
- **根因**：应用机器人（自己开发的）没有 Webhook；自定义机器人（群内置）才有
- **解法**：要么加「自定义机器人」拿 Webhook；要么用应用机器人调 `im/v1/messages` 主动发（用 chat_id）
- **预防**：先确定"发消息"用哪种身份，再设计告警通道

### 27. 长连接 vs 回调地址
- **根因**：回调地址需要公网 HTTPS（要域名/备案）；长连接（WebSocket）不需要
- **解法**：开发/小项目优先选长连接
- **预防**：架构选型时优先"不需要公网入口"的方案

### 28. 消息重复投递
- **现象**：同一条消息机器人回了两遍
- **根因**：IM 平台会重投事件
- **解法**：用 `message_id` 做去重集合（有上限地清理）
- **预防**：所有事件处理都假设"至少一次投递"

---

## 七、运维与告警

### 29. SSH 突然连不上，但端口是通的
- **现象**：TCP 连得上，但收不到 SSH banner；网页正常
- **根因**：反复失败/超时留下大量半开会话，触发 sshd 的 `MaxStartups` 保护
- **解法**：等 2 分钟自动释放；或从云控制台 VNC 进去 `systemctl restart ssh`
- **预防**：脚本重试要加退避；`MaxStartups 100:30:200`

### 30. systemd timer 的 `NEXT` 显示 n/a
- **现象**：定时器 `enabled + active`，但永远不触发
- **根因**：`OnUnitActiveSec` 依赖服务上次激活时间，冷启动时算不出来
- **解法**：改用 `OnCalendar=*:0/5`
- **预防**：写完后 `systemctl list-timers` 必须看到 NEXT 有具体时间

### 31. 健康检查服务 `status` 显示 inactive
- **现象**：以为坏了
- **根因**：`Type=oneshot` 跑完就退出，这是正常的
- **解法**：看 `journalctl -u xxx` 的历史记录，而不是 `is-active`
- **预防**：文档里写清楚"oneshot 服务 inactive 是正常状态"

### 32. 告警刷屏
- **现象**：服务挂一晚，收到几百条消息
- **解法**：状态文件 + 只在"连续 N 次失败且首次达标"时推一次
- **预防**：告警系统必须有去抖和收敛

### 33. shell 函数覆盖系统命令
- **现象**：`free -h | head -2` 输出变成 `===== -2 =====`
- **根因**：自定义了 `head()` 函数
- **解法**：改名 `section()` 等
- **预防**：不要用 `head/test/[`/`ls`/`cd` 等做函数名

---

## 八、Git 与协作

### 34. 推送被拒：远程有本地没有的提交
- **现象**：`! [rejected] main -> main (fetch first)`
- **根因**：两条开发线分叉（云端自动改 / 本地开发）
- **解法**：先 `git fetch` 看差异，再决定 merge / rebase / 推新分支
- **预防**：**不要直接在会冲突的两条线上改同一批文件**；用分支隔离

### 35. 密钥提交进 git
- **现象**：`.env` 出现在仓库里
- **根因**：`git add .` 一把梭，`.gitignore` 没配好
- **解法**：立即轮换密钥（删 commit 不够，历史里还在）；`git rm --cached`
- **预防**：第一个 commit 就写 `.gitignore`；CI 里加 secret 扫描

---

## 九、成本与选型

### 36. 学生免费机仍然会欠费
- **现象**：机器免费，账户余额却被扣到 0
- **根因**：套餐免费 ≠ 流量免费，带宽"按流量计费"照样扣钱
- **解法**：改成固定带宽计费；或预存余额
- **预防**：买机器时看清"哪些免费、哪些按量"

### 37. 云数据库 vs 云服务器
- **现象**：差点买了 ¥55/月的 RDS
- **根因**：RDS 只是数据库，跑不了应用，还得再买服务器
- **解法**：内部小项目直接在 ECS 上装 PostgreSQL（免费）
- **预防**：先画部署图（应用在哪、数据库在哪），再选产品

---

## 通用排查套路（把这套背下来）

1. **先分层**：网络 → 端口 → 进程 → 配置 → 代码
2. **拿最底层的证据**：端口能不能连？banner 有没有回？DNS 通不通？
3. **先看日志再猜**（`journalctl`、应用日志、平台日志）
4. **最小复现**：把问题从系统剥离成 10 行脚本
5. **问"最近改了什么"**：90% 的故障由最近一次变更引起
6. **换一条路验证**：curl 换 python、SSH 换控制台 VNC、HTTP 换 socket
