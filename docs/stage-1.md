# 阶段 1：最小 Agent 验收

日期：2026-10-22（Asia/Shanghai）。基于阶段 0 验收完成后的用户“继续”指令实施。本阶段只交付最小 Agent，不进入阶段 2 搜索与网页提取。

## 已完成

- FastAPI 健康检查，返回进程状态、当前阶段及本地模型配置是否有效；健康检查不发起付费请求。
- `POST /api/agent`：通过实际安装的 OpenAI Agents SDK `Agent` / `Runner.run` 和 `OpenAIChatCompletionsModel` 调用用户配置的 DeepSeek。
- 请求/响应 Pydantic Schema，服务端生成请求 ID，成功响应包含文本、模型名称、调用数、token 用量及耗时。
- 启动检查 `.env` 配置。缺少配置时明确记录 degraded 事件，健康接口仍可用于诊断，模型接口返回 503；不静默使用虚假回答。
- 每进程一个并发模型调用；总超时涵盖排队和模型调用；最大一轮 SDK 执行，禁用自动重试和 tracing。
- 输入 1–2000 字符、POST 请求体最大 32 KiB、输出最多 512 tokens / 12000 字符；请求体限制在 JSON 解析前生效，不依赖客户端 Content-Length。
- 认证失败、限流、连接失败、超时、上游错误和空输出均映射为固定错误码及中文说明，不转发上游异常正文。
- 结构化日志采用字段白名单，只记录事件、请求 ID、状态、耗时、token 用量；不记录问题、模型输出、密钥或请求头。输出中若出现当前配置的密钥则脱敏。
- 修复阶段 0 探测脚本的日志副作用：结束时恢复此前 logging.disable 状态。

## 新增及修改文件

- 新增 `deepdive/providers/llm.py`、包初始化文件：最小模型服务及错误分类。
- 新增 `deepdive/observability/logging.py`、包初始化文件：JSON 日志。
- 新增 `apps/api/schemas/agent.py`、包初始化文件：请求、响应、错误 Schema。
- 新增 `apps/api/middleware.py`：请求体大小限制。
- 新增 `tests/test_stage1.py`：成功/失败路径、SDK 适配、超时及隐私测试。
- 修改 `apps/api/main.py`：启动配置检查、API、请求 ID 和异常处理。
- 修改 `deepdive/config.py`：无效 URL 解析统一映射为配置错误。
- 修改 `scripts/smoke_model.py`：恢复日志状态。
- 修改 `tests/test_stage0.py`：健康检查适配当前阶段，并通过 lifespan 执行配置检查。
- 修改 `README.md`、`pyproject.toml`、`uv.lock`：运行说明及项目版本 0.1.0；第三方依赖版本未改变。

原规范和用户 `.env` 未覆盖，未输出密钥。

## 执行命令

```sh
.venv/bin/python -m pytest -q
UV_CACHE_DIR="$PWD/.cache/uv" uv lock --offline
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked --offline
```

真实 HTTP 验收由临时子进程运行以下服务，父进程使用 urllib 请求健康检查和模型接口，finally 中停止服务。该次调用为避免已有代理问题，启动命令临时移除了 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 及其小写形式，不修改系统代理。

```sh
.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

请求：`POST /api/agent`，JSON 为 `{"prompt":"Reply with exactly DEEPDIVE_OK."}`。

日常安装、启动、curl 调用、停止、配置与排错命令见 README。

## 测试结果

- 完整离线测试：**30 passed in 1.22s**。
- 锁文件离线同步：成功，检查 48 个平台适用依赖；未增加新第三方依赖。
- 真实健康检查：HTTP 200，`{"status":"ok","stage":"1","scope":"process","model_configured":true}`。
- 真实模型 API：HTTP 200；模型 `deepseek-flash`；返回文本精确匹配 `DEEPDIVE_OK`；响应头和正文请求 ID 一致。
- 实际 SDK 用量：requests=1，input_tokens=40，output_tokens=5；duration_ms=1100。
- 测试服务已自动停止，无新增常驻进程。请求体大小限制在该次真实模型验证后加入，随后完整离线回归通过；没有为重复验证而再次发起付费请求。
- 测试中的本地 mock token 数为夹具，与上述真实调用用量分开记录。未计算缺乏价格依据的成本数字。

## 未解决问题及范围

阶段 1 无阻塞项。当前是单进程本地最小 Agent，没有研究状态机、搜索工具、证据核验、数据库、历史任务或 UI，也没有远程认证；回答不能标记为经过来源核验的研究结论。并发限制按进程生效，运行时不要增加多 worker 以绕过限制。

模型接口启动配置失败时保持健康检查可诊断，但 `model_configured=false` 且模型接口返回 503；这是显式的降级行为，不代表 Provider 就绪。实际 Provider 可用性由探测或模型调用确认。

## 是否满足验收

**满足阶段 1 验收**：健康检查、最小 SDK Agent、明确且脱敏的失败响应及自动化测试均通过。

下一阶段建议：按规范等待用户指令进入阶段 2，封装搜索 Provider、接入搜索服务并实现带 SSRF 防护的网页提取；接入真实搜索前通过本地配置搜索服务密钥。
