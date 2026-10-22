# 阶段 4：Web 界面与历史记录

日期：2026-10-22（Asia/Shanghai）。项目版本 0.4.0。本阶段完成浏览器研究闭环，未进入阶段 5 的固定问题质量评测。

## 已完成

- 研究工作台：问题输入、示例填入、轮数/时限/搜索/候选来源/美元预算设置；在线状态与统计来自实际 API 和 Worker 锁。
- 历史记录：SQLite 持久化任务和报告，服务端筛选与分页，点击进入任务详情。
- 任务详情：实际阶段、用量、事件时间线、报告、主张与来源摘录；刷新恢复已有研究。
- SSE：数据库事件序号作为事件 ID，支持 Last-Event-ID 与 after 续传、心跳、断线重连与终结事件；15 秒真实状态读取兜底。不使用按时间增长的虚假进度条。
- 取消任务：保存幂等取消请求，等待 Worker 记录最终状态；排队取消不会启动模型调用。
- Markdown 报告：跳过原始 HTML，禁用远程图片及危险链接协议；下载原始报告。外链附加 noopener/noreferrer。
- Next.js 静态导出由现有 FastAPI 在同一端口提供，API 路由优先；未构建时给出明确 503 说明。仅监听 127.0.0.1:8000。
- 独立桌面与移动端布局；研究记录和时间显示使用 Asia/Shanghai。

## 新增/修改文件

- `apps/web/app/`：首页、历史页、任务详情、布局、样式与图标；`apps/web/components/`、`apps/web/lib/api.ts`。
- `apps/web/next.config.ts`、TypeScript 配置、`apps/web/package.json`、根 `package.json`、`package-lock.json`、`.npmrc`。
- `apps/api/main.py`、`apps/api/routes/research.py`、`deepdive/storage/database.py`、新增 `deepdive/storage/worker_status.py`：静态资源、健康状态、统计筛选、报告下载、持久化 SSE 和取消事件。
- `deepdive/providers/llm.py`、`deepdive/orchestration/controller.py`、`deepdive/agents/planner.py`、`researcher.py`、`verifier.py`：结构化输出开启 JSON mode，提示词包含实际 Schema，校验失败保存安全诊断，不保存原始模型正文。
- `tests/test_stage4.py`、相关 SDK/编排测试；`apps/web/tests/workspace.spec.ts`、Playwright 配置；`scripts/check_live_ui.mjs`、`scripts/preview_web.mjs`。
- `README.md`、`.gitignore`、`pyproject.toml`、`uv.lock`、本记录。用户密钥与既有研究数据保留。

## 依赖与部署选择

前端锁定 Next.js 16.4.2、React/React DOM 19.3.1、react-markdown 10.1.0、TypeScript 7.0.2、Playwright 1.64.1。构建使用项目内 Node 24.22.1，不更改全局 Node。Python 环境继续使用现有 3.11.4，无新增 Python 第三方依赖。

官方 npm 端点在本机出现 CERT_NOT_YET_VALID，项目 `.npmrc` 使用 TLS 验证正常的 npmmirror，strict-ssl=true。已实际执行缓存离线重装，0 vulnerabilities。该 npm 版本的 `npm ci --dry-run` 也可能先清理 node_modules，故不将它作为只读检查。

采用 [Next.js 官方静态导出方式](https://nextjs.org/docs/app/guides/static-exports)，日常服务无需第二个 Node 进程。动态任务 ID 使用 `/task/?id=...`。SSE 使用 [FastAPI StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/)，结构化模型调用使用 [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)。JSON mode 不替代 Schema 校验与逐字证据校验。

## 执行命令

```sh
npm ci
npm run typecheck
npm run build:web
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.run_local
# 另一个终端；常规浏览器测试拦截 API，不产生模型费用
npm run test:web
# 只读现有任务，生成页面截图
node_modules/node/bin/node scripts/preview_web.mjs
# 显式付费验收：创建受限研究与排队取消任务，保留记录
node_modules/node/bin/node scripts/check_live_ui.mjs
```

已启动 API 与独立 Worker，首页为 http://127.0.0.1:8000/ 。停止使用运行终端的 Ctrl-C；重新启动使用 scripts.run_local。真实验收临时移除进程代理环境变量沿用此前已验证的直连方式，没有改动系统代理。

## 测试结果

- Python：**124 passed in 4.98s**，覆盖既有研究闭环，以及 SSE 重放/续传/任务隔离/非法游标/断线、幂等取消、实际统计/筛选/下载、Worker 锁和 SDK JSON mode 请求。
- 浏览器：**5 passed in 5.2s**，覆盖创建与设置提交、报告/刷新、历史筛选、危险 Markdown、移动端宽度和无效任务错误。这 5 项使用明确 API 夹具，不作为真实模型成功证据。
- TypeScript 检查与生产静态构建通过，路由包含首页、history、task 和图标。
- 使用本机 Google Chrome 155 执行真实 UI 验收，页面创建研究、观察真实 SSE、刷新恢复、下载与历史筛选均通过，浏览器 JavaScript 错误为 0。
- 独立审计：9 条证据摘录均逐字存在于对应存储来源正文；下载的 Markdown 与数据库报告完全一致。
- 客户端构建的 35 个 HTML/JS/JSON/TXT 文件与现有 `.env` 密钥值比对，未发现密钥；检查不输出密钥。

## 真实验收记录与失败保留

| 任务 ID | 结果 | 验收 |
| --- | --- | --- |
| d04f982a8d874a1e99ae052bdbf36a9c | FAILED / invalid_model_output | 保留为失败，不计通过 |
| 8a79954c9a8f4abfb58a466ddd2dfbad | 排队取消，0 次模型调用 | 取消通过 |
| **62fddbfa3c674766a5bd4a13cfd8e130** | **COMPLETED；13 个有效来源、4 条主张、9 条证据关联** | **完整浏览器流程通过** |
| cdc00802c470439fbe12a064985f08d5 | 排队取消，0 次模型调用 | 取消通过 |

首次真实研究暴露结构化输出不符合 Schema，页面如实显示失败。修复通过启用 JSON mode、将实际 Pydantic Schema 纳入角色提示词并保存安全的校验错误类型完成；未放宽逐字摘录规则，也未添加自动付费重试。失败数据在 `data/ui-live/initial-failure.json` 与数据库中保留。

通过研究的实际用量：1 轮、2 次 Search、20 次 Fetch 尝试、3 次模型调用；输入 5951 tokens、输出 1119 tokens，耗时 46.318 秒。2 条主张为 SUPPORTED，2 条为 PARTIALLY_SUPPORTED。有效来源数量不代表独立出版机构数量。

美元上限 0.25，按记录单价保守估算 0.0196281 USD，调用前累计费用预留 0.046323 USD；估算忽略缓存、优惠与失败请求减免，不是实际账单。

结果保存于 `data/ui-live/result.json`，原始下载为 `data/ui-live/report-62fddbfa3c674766a5bd4a13cfd8e130.md`。实际页面截图在 `data/ui-live/report.png`、`progress.png`，只读桌面与移动端截图在 `data/ui-preview/`。这些本地验收产物不纳入源码依赖。

## 未解决问题

- 尚未进行至少十题质量评测；单个基础事实问题通过不代表复杂比较、冲突信息或时效信息均可靠，阶段 3/4 的真实失败样例保留。
- DeepSeek 远端 Fetch 未提供可审计重定向链，沿用明确的 redirect_chain_verified=false 边界，不宣称验证每一跳。
- 当前仅本机使用，无公网认证；未实施阶段 6 部署。当前机器为 macOS arm64，尚未实测 Intel 平台。

## 是否满足验收与下一阶段建议

**满足阶段 4 验收**：浏览器创建并查看完整研究、真实事件与状态一致、刷新恢复任务与报告、取消可用，未使用虚假进度。按规范等待用户指令进入阶段 5，再建立至少十个固定问题、明确引用/支持度/事实错误/覆盖率计算方法，并比较研究策略与费用。
