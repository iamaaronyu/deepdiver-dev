# 阶段 3：证据驱动研究闭环

日期：2026-10-22（Asia/Shanghai）。按用户“继续”指令实施阶段 3，未进入阶段 4 的 Web UI / SSE 展示。

## 已完成

- Planner：实际 Agents SDK 模型调用生成受 Schema 校验的子问题、优先级、目标和证据类型；补充研究根据实际证据缺口重新规划。
- Researcher：调用已配置的 DeepSeek Search/Fetch 来源采集器；优先选取与问题相关的实际正文窗口，由模型选择片段 ID 关联候选主张。逐字匹配失败、未知来源/片段 ID 不会被伪装为证据。
- Verifier：独立模型上下文判断支持、反证和上下文关系；再通过同任务来源、逐字定位、词面关联、域名交叉核验和时效性规则，保守分类 SUPPORTED / PARTIALLY_SUPPORTED / CONTRADICTED / UNVERIFIED / OUTDATED_RISK。模型自评不是唯一依据。
- Writer：确定性渲染真实主张、证据、位置与 URL，包含执行摘要、关键结论、分主题分析、冲突与不确定性、局限、来源清单和用量。不让模型自由编造 URL/作者/日期；生成时间使用 Asia/Shanghai。
- 显式状态机与有限补充研究；正常完成及 FAILED / CANCELLED / BUDGET_EXCEEDED / TIMED_OUT 均持久化，尽可能生成不额外调用模型的部分报告。
- 请求、抓取、模型次数、token、轮数、总时限与可选美元上限。调用前保守预留最坏重试/输出预算，用量缺失时金额返回 null 并标记不完整，不假造实际账单。
- SQLite 持久化 ResearchTask、ResearchSubtask、Source、Evidence、Claim、ClaimEvidence、Report 和带时间戳的事件；外键启用，WAL 模式，新增式初始化迁移，保留既有阶段 2 数据。
- 独立本地 Worker 读取 SQLite 队列，OS 文件锁确保单一所有者；取消可中断等待模型/工具调用；崩溃后重启会将中断运行任务标记 FAILED（worker_restarted），保留材料，CREATED 任务继续排队。
- `scripts.run_local` 管理 API 与 Worker 两个独立进程，Ctrl-C 优雅停止；后台研究不依赖 FastAPI BackgroundTasks。
- 一致性 SQLite backup API，备份包含任务、完整正文、证据及报告。

## API

- `POST /api/research`：校验问题与配置，返回 202 和持久化任务 ID。
- `GET /api/research/{id}`：真实任务状态、配置与用量。
- `GET /api/research`：limit/offset 分页历史。
- `GET /api/research/{id}/evidence`：类型化的主张、来源摘要、摘录和关联关系。
- `GET /api/research/{id}/report`：text/markdown；未生成 409、不存在 404。
- `POST /api/research/{id}/cancel`：持久化取消请求，终结任务不会重跑。

健康检查仍表示 API 进程与本地配置状态，不执行付费请求，也不保证 Worker 活跃。必须使用 run_local 或另启独立 worker。SSE 接口与 Web 操作页留待阶段 4。

## 新增/修改文件

- 新增 `deepdive/orchestration/models.py`、`state_machine.py`、`budget.py`、`pricing.py`、`controller.py`。
- 新增 `deepdive/agents/planner.py`、`researcher.py`、`verifier.py`、`writer.py`。
- 新增 `deepdive/storage/database.py`、`migrations/001_initial.sql`、`deepdive/worker.py` 及包初始化文件。
- 新增 `apps/api/routes/research.py`、`apps/api/schemas/research.py`。
- 新增 `scripts/run_local.py`、`smoke_research.py`、`backup_state.py`。
- 新增 `tests/test_stage3.py`；调整现有测试隔离数据目录与阶段标识。
- 修改 `deepdive/providers/llm.py`，在内部支持角色提示和输出上限，保留原单轮接口行为。
- 修改 `apps/api/main.py`、`deepdive/evidence/repository.py`、`README.md`、`pyproject.toml`、`uv.lock`。
- 项目版本 0.3.0，未新增第三方依赖。用户 .env、规范原文和原始来源记录未覆盖。

## 执行命令

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv lock --offline
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked --offline
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.run_local
# 另一个终端
.venv/bin/python -m scripts.smoke_research
.venv/bin/python -m scripts.backup_state
```

真实部署启动命令临时移除了 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 的大小写环境变量，以保持与前期已验证的直连路径一致，未修改系统代理。默认仍仅监听 `127.0.0.1:8000`。

## 测试结果

- **111 passed in 4.14s**。
- 覆盖完整离线研究闭环、真实来源引用、伪造摘录拒绝、未知片段/核验 ID 拒绝、跨任务关联拒绝、来源冲突、重要单域名主张部分支持、补充轮数限制及证据合并、搜索/token/美元预留上限、超时/取消、异常输出、模型失败、Worker 独占及崩溃恢复、历史/API/报告、并发数据库初始化等。
- 首次部署暴露 API/Worker 并发创建 SQLite 的竞争，已通过初始化锁重试和监督进程预初始化修复，新增四路并发初始化回归测试。
- 数据库 `integrity_check=ok`，`foreign_key_check` 零错误。
- SQLite 备份已实际生成并读回，完成任务状态与 6 条证据均存在。备份位于 `data/backups/20261021T230756Z-7c246b9d.sqlite3`（文件名为 UTC 时间，快照在报告本地时间 v2 导出前生成）。

## 真实研究验收与保留的失败样例

所有任务使用现有本地 DeepSeek 配置，不把离线夹具当实际结果。

| 任务 ID | 问题/版本 | 实际结果 | CLI 验收 |
| --- | --- | --- | --- |
| 8e8f1af828934dc38709d5ce8009d75f | TaskGroup 与 gather 异常比较；初版自由摘录 | 4 个有效来源、3 条未核实主张、0 条逐字匹配证据；报告明确证据不足 | 退出 1，不通过 |
| 2de485c265d64a3d8f4d1628fbb0a428 | 同一比较问题；片段 ID 初版 | 7 个有效来源，检索/选段不足以支撑问题，0 条主张/证据 | 退出 1，不通过 |
| **9247aced17d24589b025ba1a9b6e3f1d** | **What is Python asyncio and what kinds of applications use it? Prefer official documentation.** | **17 个不重复有效正文来源，4 条主张，6 条证据关联；2 SUPPORTED、2 PARTIALLY_SUPPORTED** | **退出 0，通过最小闭环** |

前两轮流程状态为 COMPLETED，但 CLI 因没有实际证据关联而拒绝验收，未伪造引用或删除失败结果。为修复实际问题，Researcher 改为服务端原文片段 ID，并改进长正文相关窗口定位；复杂比较问题的检索质量仍需阶段 5 评测改进，不能由基础事实样例推断一般质量。

通过任务实际用量：

- 1 个研究轮次；2 次 Search、20 次 Fetch 尝试。
- 3 次模型调用；输入 4599 tokens、输出 872 tokens。
- 耗时 54.175 秒；样例设置的 180 秒及 0.25 美元快照上限未触发。
- 保守用量估算 0.0189261 USD，调用前累计费用预留 0.0452571 USD；按 2026-10-22 峰时未缓存输入/输出与工具请求单价计算，忽略优惠、失败减免和缓存，不代表账单。
- 6 条摘录全部再次确认属于对应任务保存的实际正文；17 个有效来源的规范化 URL、正文哈希分别唯一，报告来源链接均来自这些记录。
- 17 个 URL/哈希唯一不表示 17 个独立出版方：包含 Python 文档不同版本和语言；重要主张同域名交叉引用仍只标 PARTIALLY_SUPPORTED。

真实样例：

- `data/reports/9247aced17d24589b025ba1a9b6e3f1d-v1.md`：Worker 初次生成，保留。
- `data/reports/9247aced17d24589b025ba1a9b6e3f1d-v2.md`：同一证据材料的本地时间显示导出，未额外调用 Provider，数据库和事件中保留版本。
- API：`http://127.0.0.1:8000/api/research/9247aced17d24589b025ba1a9b6e3f1d/report`。

API/Worker 最终重启后，真实 HTTP 验证任务仍为 COMPLETED、证据仍为 6 条，报告 HTTP 200、text/markdown，并显示 Asia/Shanghai。服务当前保持运行。

## 技术决定与已知问题

- 模块化单体 + 独立本地 Worker + SQLite，未引入 Redis/Celery/Kubernetes；API 不持有后台研究执行。
- Writer 使用确定性渲染，保证引用路径来自实际记录；不额外调用写作模型。
- 自动语义核验结合字面锚点和来源规则仍可能误判，跨语言转述会更保守；域名不同也不等于内容独立。
- 基础事实闭环通过，特定比较题在单轮限制下未形成证据关联，已保留；尚未开展十题评测或宣称准确率。
- DeepSeek Fetch 不提供最终跳转链；仍明确记录供应商抓取，不能声称本地核验远端全部跳转。
- 费用快照仅支持已识别的官方 DeepSeek Flash + DeepSeek Search/Fetch；其他组合不能开启美元上限，只使用请求/token/时限。价格变化后需更新快照，不能据此保证实际账单。预留最坏重试预算会提前停止，未用完的金额预留不回收。
- Worker 异常退出后不自动重试付费任务；重新启动会清理运行状态并保留材料。Mac 休眠/断网会影响运行，应重新检查任务状态；远程认证与运行加固在阶段 6。

## 是否满足验收与下一步

**满足阶段 3 的最小工程验收**：真实规划、搜索、核验、报告闭环通过；主张与实际摘录/URL 关联；不足时明确标记；轮数、请求、token、预算与时限均有停止路径；失败/重启不伪装继续运行。保留的质量失败不被计为通过。

下一阶段建议：按规范等待用户指令进入阶段 4，创建研究输入、任务列表、详情与报告 Web 页面，并基于持久化事件提供真实 SSE 进度和取消操作。

价格依据：[DeepSeek 官方模型与工具定价](https://api-docs.deepseek.com/quick_start/pricing/)。API 与密钥安全使用方式沿用阶段 0–2 已验证实现。
