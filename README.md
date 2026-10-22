# DeepDive 本地研究工作台

完整架构、研究链路、关键代码、数据模型与运维说明见 [DeepDive 整体架构与实现说明](docs/DeepDive_整体架构与实现说明.md)。

现在可直接打开 http://127.0.0.1:8000/ 使用研究工作台：输入问题、设置预算、查看真实进度、取消任务、阅读报告和追溯证据。Next.js 静态前端、FastAPI API 和独立 Worker 共用现有本地部署，SQLite 保存研究记录。健康检查不发起付费请求。

商务报告版已加入更易读的报告排版、目录、证据跳转与打印样式。工作台默认“深度研究”：补查独立视角、比较与边界；模型基于证据综合分析后，再由独立上下文审查各段是否超出材料。旧报告不会自动重跑或产生费用。详细变更与真实样例见 [商务报告与研究深度改进](docs/business-research-upgrade.md)。

## 安装

需要 Python 3.11–3.13、uv 和用于首次安装的 Node >=20.9 / npm。当前机器使用 Python 3.11.4；前端构建使用项目内锁定 Node 24.22.1，不修改系统 Python 或全局 Node。

```sh
uv sync --locked --python 3.11
npm ci
npm run build:web
```

其他机器可将 `--python` 改为自己的 Python 3.11 路径。Python 与前端依赖分别由 `uv.lock` 和 `package-lock.json` 锁定，不安装到全局环境。`.npmrc` 仅设置本项目的镜像与缓存，strict-ssl 保持 true：本次官方 npm 端点实际出现 CERT_NOT_YET_VALID，已使用 TLS 验证正常的 npmmirror 镜像安装。缓存完整时已验证 `npm ci --offline` 可重装；不要用 `npm ci --dry-run` 做无副作用检查，该 npm 版本可能先清理 node_modules。前端变更后重新执行 build:web；日常运行仅需 Python，不另开 Node 运行端口。

## 配置 DeepSeek

本项目 `.env` 已由用户在本地配置，创建时权限为 600。不要覆盖已有配置。如果其他机器没有此文件，先执行：

```sh
(umask 077; cp -n .env.example .env)
```

在本地编辑器中填写 `.env` 的 `DEEPSEEK_API_KEY`，不要将密钥发到聊天或写入代码。

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
MODEL_TIMEOUT_SECONDS=60
OPENAI_AGENTS_DISABLE_TRACING=1
```

模型名称取自本次读取的 DeepSeek 官方文档，可按账号实际可用模型修改。进程环境变量优先于 `.env`。项目使用 OpenAI Agents SDK 的 `OpenAIChatCompletionsModel` 连接 DeepSeek，不使用默认 Responses API。Tracing 在调用配置中强制关闭。探测禁用 thinking、最多 128 输出 token、一次调用且不自动重试；仍可能产生少量 API 费用。

## 验证与启动

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.smoke_model
.venv/bin/python -m scripts.run_local
```

`scripts.run_local` 同时启动 API 和独立 Worker，Ctrl-C 优雅停止两者。只启动 Uvicorn 时，新研究任务会停留在 CREATED，必须另开终端执行 `.venv/bin/python -m deepdive.worker`。Worker 使用 OS 文件锁，每个数据目录只能有一个 Worker。

浏览器访问 `http://127.0.0.1:8000/` 即可使用研究页面；`/history/` 查看历史，`/task/?id=<task_id>` 查看任务。静态导出由同一个 FastAPI 服务提供，API 使用同源路径，不需要 CORS 或第二个端口。

另开终端检查：

```sh
curl --fail http://127.0.0.1:8000/api/health
```

配置正常时响应为 `{"status":"ok","stage":"4","scope":"process","model_configured":true,"search_configured":true,"worker_running":true}`。前台服务使用 Ctrl-C 停止。

最小 Agent 调用（每次产生一次真实模型请求）：

```sh
curl --fail-with-body http://127.0.0.1:8000/api/agent \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"用一句话解释什么是证据驱动研究。"}'
```

返回 `request_id`、`answer`、`model`、`usage`（请求次数、输入/输出 tokens）和 `duration_ms`。`X-Request-ID` 响应头与返回值一致。回答未经过搜索或来源核验，不作为研究报告。

输入为 1–2000 字符，请求体最大 32 KiB；输出最多 512 tokens、12000 字符。默认每个服务进程最多同时执行一个模型请求；配置超时包含排队时间。关闭自动重试，避免重复计费。启动时校验配置但不自动调用模型；修改 `.env` 后需重启服务。

API 错误统一返回 `{"request_id":"...","error":{"code":"...","message":"..."}}`：

| HTTP | 场景 |
| --- | --- |
| 413 / 422 | 请求体过大 / 输入不合法 |
| 503 | 模型未配置或 Provider 限流 |
| 502 | 认证失败、网络错误、上游错误或无效输出 |
| 504 | 模型调用或排队超时 |

结构化 JSON 日志仅包含事件、请求 ID、状态、耗时及 token 用量，不记录 prompt、模型正文、密钥、请求头或上游错误正文。Tracing 关闭，第三方 SDK 日志禁用。

模型探测成功返回 `status=ok` 和实际 token 用量；未配置返回退出码 2，调用失败返回退出码 1。错误只输出固定说明和异常类型，不输出上游响应正文或密钥。不得将离线测试或健康检查当作真实模型调用结果。

## 故障排查

- `configuration_error`：检查本地 `.env` 中是否填写密钥、模型名称和正确的 HTTPS 地址。
- `AuthenticationError`：检查 DeepSeek 密钥和账号权限。
- `APIConnectionError` / 超时：检查网络及 `HTTPS_PROXY` 等代理；本机曾出现 `127.0.0.1:1087` 代理不可达现象。不要为解决网络问题提交密钥。
- `BadRequestError` / `NotFoundError`：确认账号支持所配置模型及 Chat Completions 参数。
- 端口已被占用：改用其他本地端口，避免停止未知的已有进程。
- 系统默认 Python 3.9.6 不符合当前依赖要求，使用 `.venv/bin/python`。

## 安全、数据和后续

`.env`、虚拟环境、缓存、未来的数据库和报告目录均被 `.gitignore` 排除。Git 仓库只提交源码、依赖锁文件、测试和文档，不提交本地密钥与运行数据。默认仅监听回环地址；此阶段没有认证，不应改为公网绑定。

数据库位于 `data/research.sqlite3`（WAL 模式），启动时只执行新增表的初始化迁移，版本记录在 `PRAGMA user_version`；不删除或替换已有数据。完整来源、证据和报告同时保存在 SQLite；Markdown 导出在 `data/reports`，原始采集集合在 `data/sources`。可通过 `DEEPDIVE_DATA_DIR` 设置其他数据目录，API 和 Worker 必须使用相同值。

一致性备份（包括任务、完整来源、证据与 Markdown 报告）：

```sh
.venv/bin/python -m scripts.backup_state
```

使用 SQLite backup API，将快照写入 `data/backups` 的唯一文件（权限 600），无需直接复制正在写入的 WAL 数据库。若要保留独立导出和采集诊断文件，停止服务后另行复制 `data/reports` 与 `data/sources`。密钥单独安全保管，不纳入数据备份；恢复前先停机并保留现有数据库及其 WAL/SHM 文件，不自动覆盖用户数据。轮换密钥后重启并运行模型探测。

## 阶段 4：Web 工作台与真实进度

- 工作台：输入研究问题，通过“研究设置”选择轮数、时限、搜索数、候选来源数和可选美元上限。示例按钮只填入问题，不会自动调用付费服务。
- 研究记录：服务端状态筛选与分页，统计来自真实数据库，不使用演示数字。
- 任务详情：阶段、事件、用量、报告、主张和实际证据。刷新会从 SQLite 恢复；没有按时间自动增长的百分比进度条。
- 取消：确认取消请求已保存后显示“正在取消”，最终状态以 Worker 写入的 CANCELLED 为准；排队任务也可取消。
- 报告：安全渲染 Markdown，跳过原始 HTML，禁用远程图片与非 HTTP/HTTPS 链接；外部来源链接使用 noopener/noreferrer。可下载原始 Markdown。
- 页面“研究服务在线”要求模型/搜索配置和 Worker 锁均有效；这表示本地服务就绪，不代表供应商永远可达或研究结论已核实。

SSE：`GET /api/research/{task_id}/events` 按数据库序号发送具备 id、event、JSON data 的持久化事件。支持 `Last-Event-ID` 和 `?after=<id>` 续传、10 秒无事件心跳、终结时 stream.end；未知任务/游标错误在开始流前返回 JSON。页面断线会自动重连，另有 15 秒真实状态读取兜底。

报告下载：`GET /api/research/{task_id}/report?download=true`。研究列表响应头 `X-Total-Count` 提供筛选后的总数，`GET /api/research/summary` 提供真实全局计数。

前端检查：

```sh
npm run typecheck
npm run build:web
npm run test:web
```

浏览器测试使用本机 Google Chrome（Playwright 独立临时配置）；6 项常规测试拦截 API，不消耗模型费用。`node_modules/node/bin/node scripts/preview_web.mjs` 对现有数据只读截图。显式真实验收脚本如下，会创建一项受限付费研究及一项排队取消验证任务，并保留研究记录：

```sh
node_modules/node/bin/node scripts/check_live_ui.mjs
```

初次前端未构建时首页返回清晰的 503 构建说明；API 路径继续可用。当前只允许本机访问，没有公网认证或托管部署。前端构建产物、node_modules、截图、浏览器 trace 均被忽略；源码和依赖锁可重建页面。构建产物不包含 .env 或后端密钥。

## 阶段 3：研究闭环

创建任务（返回 HTTP 202 和任务 ID，后台由独立 Worker 执行）：

```sh
curl --fail-with-body http://127.0.0.1:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do asyncio TaskGroup and gather differ on errors?","settings":{"max_rounds":1,"max_budget_usd":0.25}}'
```

将返回的任务 ID 替换下方 `<task_id>`：

```sh
curl http://127.0.0.1:8000/api/research/<task_id>
curl http://127.0.0.1:8000/api/research/<task_id>/evidence
curl http://127.0.0.1:8000/api/research/<task_id>/report
curl -X POST http://127.0.0.1:8000/api/research/<task_id>/cancel
curl 'http://127.0.0.1:8000/api/research?limit=20&offset=0'
```

报告未生成返回 409；未知任务返回 404。取消请求持久化，Worker 在等待外部调用时也会检测并取消，保存已有材料和部分报告；已终结任务不会重新运行。

完整真实验收：

```sh
.venv/bin/python -m scripts.smoke_research
```

任务状态：CREATED → PLANNING → RESEARCHING → VERIFYING → WRITING → COMPLETED；证据不足可进入 NEEDS_MORE_RESEARCH 再研究。失败、取消、预算和总超时分别记录 FAILED / CANCELLED / BUDGET_EXCEEDED / TIMED_OUT，尽可能生成不再调用模型的部分报告。Worker 重启取得独占锁后，将中断的运行任务标记 FAILED（worker_restarted），保留材料，排队的 CREATED 任务继续执行；不自动重试付费研究。

研究模式（通过 settings.depth）：standard 为标准研究，deep 会在轮数/预算允许时补查第二视角。Web 默认深度模式，API 未指定时保留 standard。深度模式单次模型调用最长 180 秒，仍受任务总时限约束；其余调用使用 MODEL_TIMEOUT_SECONDS。

可配置上限（通过 settings）：max_rounds=3、max_search_requests=30、max_fetch_requests=60、timeout_seconds=600、max_sources_per_query=5、max_model_calls=12、max_total_tokens=64000；max_budget_usd 默认不设置。搜索前预留一次重试的最坏请求数，因此剩余预算不足两次搜索尝试或整批 Fetch 时，会提前停止；模型调用也使用 UTF-8 字节数加协议余量预留输入，再按实际 SDK token 用量记录。未用完的最坏费用预留不回收，以保证保守性。

美元预算仅在已识别的官方 DeepSeek Flash + DeepSeek Tools 组合下启用；其他组合没有单价快照时返回 pricing_unavailable。当前估算按 [2026-10-22 官方价格快照](https://api-docs.deepseek.com/quick_start/pricing/)的峰时未缓存输入、输出及工具每请求单价，忽略缓存优惠、失败减免和活动；属于保守工程估算，不是账户账单。价格变化后应更新 `deepdive/orchestration/pricing.py`。即使不设置美元上限，请求、token、轮数和时限仍生效；模型用量不可得时金额返回 null 并标记不完整。

引用核验：Researcher 从实际正文选取逐字片段，模型仅引用片段 ID；数据库再次检查同一任务、实际来源和正文匹配。Verifier 独立检查语义关系，并结合逐字定位、词面关联、来源域名和时效性给出 SUPPORTED / PARTIALLY_SUPPORTED / CONTRADICTED / UNVERIFIED / OUTDATED_RISK。重要主张缺少不同域名交叉核验时最多部分支持；跨语言或弱词面关联不会仅凭模型自评标记已支持。

Synthesizer 根据已有支持/部分支持主张生成核心判断、主题分析、决策启示和待查问题；独立上下文按实际摘录审查每段，移除超出证据的扩展。未知引用或有效分析不足时回退到证据报告。Writer 使用确定性 Markdown 渲染，所有来源 URL 和摘录由数据库解析，不让模型自由生成引用。报告保留证据附录、冲突与不确定性、局限和来源清单。同站点新旧版本材料不会混用于未限定版本的当前主张。自动支持判断可能出错，域名不同也不保证来源独立；质量评测在阶段 5 完成。

## 阶段 2：DeepSeek Search / Fetch

默认搜索和网页读取直接复用 `.env` 中已有的 `DEEPSEEK_API_KEY`，无需 Tavily 密钥。可显式指定：

```dotenv
SEARCH_PROVIDER=deepseek
```

修改配置后重启服务。搜索是独立原始 JSON API，不调用 Chat Completions 来模拟联网：`POST https://api.deepseek.com/v1/tools/search`（query/count/need_content），再对实际结果 URL 调用 `/v1/tools/fetch` 获取 Markdown 正文。搜索摘要不作为已抓取正文。

真实验收命令：

```sh
.venv/bin/python -m scripts.smoke_search "site:docs.python.org asyncio tasks queues streams subprocess synchronization"
```

每次最多一次搜索（瞬时错误最多重试一次）及 10 个候选页面的 Fetch。问题长度 1–128 个 Unicode 字符；来源数 1–10。至少 5 个不重复有效正文来源才退出 0；不足退出 1，未配置退出 2。搜索和 Fetch 可能按成功请求计费，用量记录请求尝试次数和成功内容响应数，不虚构 token 或金额；价格以 [DeepSeek 官方说明](https://api-docs.deepseek.com/guides/search/) 为准。

API 调用：

```sh
curl --fail-with-body --max-time 160 http://127.0.0.1:8000/api/sources \
  -H 'Content-Type: application/json' \
  -d '{"question":"site:docs.python.org asyncio tasks queues streams subprocess synchronization","max_results":10}'
```

返回 collection ID、状态、有效来源数、用量和来源摘要；完整正文、URL、抓取时间、标题、可得出版方/搜索服务报告的日期、哈希及失败/重复状态保存至 `data/sources/<id>.json`。未知作者/日期为 null。API 摘录最多 1000 字符，正文最多 50000 字符并标记截断；响应读取最大 2 MiB。文件默认权限 600，目录创建权限 700，已被 Git 忽略；备份时复制 `data/sources` 并妥善保管问题和抓取材料。

来源状态包括 `FETCHED`（实际正文至少 80 字符）、`FAILED`、`DUPLICATE_URL`、`DUPLICATE_CONTENT` 和超时取消的 `CANCELLED`。`FETCHED` 表示取得正文，不代表主张已核实。最多 5 路 Fetch，并发集合数为每进程 1；集合总期限 150 秒包含排队，单个 Fetch 20 秒包含 URL 检查和 API 请求；认证/余额/安全拒绝不重试，网络、限流及可重试 5xx 最多重试一次。

提交 Fetch 前，本地拒绝不允许的协议、端口、URL 用户信息，以及 DNS 返回的本机、私网、元数据、特殊和 IPv6 转换地址。请求只发到固定 DeepSeek 官方 HTTPS 端点；网页内容作为数据，不执行页面脚本或命令。**DeepSeek 服务端抓取的 DNS 和重定向链由供应商控制，当前 API 不返回最终 URL/跳转链**。因此 `fetch_provider=deepseek_fetch`、`redirect_chain_verified=false`，canonical_url 仅为提交 URL 的规范化版本，不宣称本地已验证全部跳转。网站可达性、正文正确性和主张支持度需后续核验。

可选兼容路径：显式设置 `SEARCH_PROVIDER=tavily` 并配置 TAVILY_API_KEY 时，使用保留的 Tavily + 本地 HTTPX/Trafilatura 适配器；本地抓取逐跳校验并固定公网 IP、保留 TLS SNI、限制 5 次跳转、每页 2 MiB、20 秒总超时。此路径拒绝压缩响应、PDF 和依赖 JavaScript 渲染的页面，成功时 `redirect_chain_verified=true`。两种路径的正文都不能视为自动事实核实。

阶段 0 环境记录见 [docs/stage-0.md](docs/stage-0.md)，阶段 1 变更和验收见 [docs/stage-1.md](docs/stage-1.md)。阶段 2 验收记录见 [docs/stage-2.md](docs/stage-2.md)。阶段 3 验收记录见 [docs/stage-3.md](docs/stage-3.md)。阶段 4 记录见 [docs/stage-4.md](docs/stage-4.md)。阶段 5 固定问题质量评测与成本控制见 [docs/stage-5.md](docs/stage-5.md)。已完成 10 题、两策略共 20 次基线评测；深度模式完成率 40%，质量门槛尚未通过。

### 固定质量评测

```sh
.venv/bin/python -m deepdive.evaluation.runner --live --total-budget 2
.venv/bin/python -m scripts.report_evaluation data/evaluations/运行目录
```

真实调用需要 `.env` 配置且显式传入 `--live`；最多 20 次尝试，默认总预算上限 2 美元。失败及中断保留，未知成本不按零计算。指标、限制、续跑及基线详见 [阶段 5 记录](docs/stage-5.md)。
