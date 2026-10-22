# 阶段 0：环境检查与技术验证

检查日期：2026-10-22（Asia/Shanghai）。实施范围遵循原规范第 12 节：只执行阶段 0，真实模型调用和健康检查通过后等待进入阶段 1。

## 环境

| 项目 | 实际结果 |
| --- | --- |
| 系统 | macOS 26.5.1，Build 25F80 |
| CPU 架构 | arm64（Apple Silicon）；本机未做 Intel 实机测试 |
| 默认 Python | /usr/bin/python3，3.9.6，不用于项目 |
| 项目 Python | /Users/tyu/anaconda3/bin/python3.11，3.11.4 |
| uv | 0.10.12 |
| Node / npm | 20.10.0 / 10.2.3；阶段 0 不创建前端，不安装 Node 依赖 |
| Git | 2.50.1 (Apple Git-155)；当前目录不是 Git 仓库 |
| Docker | CLI 24.0.5；守护进程访问被沙箱限制，运行状态未确认；本次不依赖 Docker |
| 原始目录 | 仅有 DeepDive_本地部署与实现规范_Agent执行版.md；原文保留 |
| 密钥检查 | 初始项目无 .env；进程未配置 OPENAI_API_KEY / OPENAI_MODEL / TAVILY_API_KEY 等被检查变量，仅报告是否存在，未读取值到输出 |
| Provider | 用户选择 DeepSeek；使用项目 DEEPSEEK_API_KEY 配置，不复用 Codex 身份凭证 |

## 依赖及技术决定

从 PyPI 官方元数据确认版本和 Python 要求后，固定直接依赖：

| 包 | 版本 | 用途 |
| --- | --- | --- |
| openai-agents | 0.24.0 | Agent / Runner，MIT 许可证，包元数据要求 Python >=3.10 |
| fastapi | 0.159.1 | 最小进程健康检查 |
| uvicorn | 0.54.0 | 本地 ASGI 服务 |
| python-dotenv | 1.2.4 | 本地配置 |
| pytest | 9.1.1 | 离线验证 |
| httpx | 0.28.1 | FastAPI TestClient |

项目选择已有 Python 3.11.4，`requires-python` 为 >=3.11,<3.14。`uv.lock` 保存传递依赖的精确版本、来源和哈希。使用项目独立 `.venv`，不修改全局包。

SDK 官方示例使用 `Agent` 和 `await Runner.run(...)`。DeepSeek 官方文档使用 Chat Completions，因此明确配置 `OpenAIChatCompletionsModel` 与独立 `AsyncOpenAI` 客户端，避免 SDK 默认 OpenAI Responses 路径。默认模型名称 `deepseek-flash` 来自本次读取的 DeepSeek 官方页面，支持通过配置修改。真实可用性仍须账号调用确认。

探测设总超时、禁用自动重试和 tracing，只接受精确的 `DEEPDIVE_OK` 响应，并记录 SDK 返回的实际 token 数。配置中的密钥不进入 repr、HTTP 返回值或异常输出。默认服务仅绑定 127.0.0.1。

阶段 0 无需数据库初始化、搜索、完整 UI 或研究报告；这些在后续阶段验收。

## 文件

- `.python-version`、`pyproject.toml`、`uv.lock`：解释器和依赖锁。
- `.gitignore`、`.env.example`：安全配置模板和忽略规则；本地 `.env` 权限 600，空密钥。
- `apps/api/main.py`：`GET /api/health`，明确仅反映进程存活。
- `deepdive/config.py`：DeepSeek 配置校验和密钥隐藏。
- `scripts/smoke_model.py`：单次真实调用验收入口。
- `tests/test_stage0.py`：健康检查、缺失配置、超时/地址校验、异常脱敏。
- `README.md`：安装、配置、运行、停止、排查与恢复说明。

## 命令

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --python /Users/tyu/anaconda3/bin/python3.11
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.smoke_model
.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
curl --fail http://127.0.0.1:8000/api/health
```

初次网络检查受到本地代理连接失败影响；后续通过授权联网完成 PyPI 元数据查询。Docker 检查失败并未被解释为 Docker 未运行。

## 验收记录

- 已完成：项目虚拟环境安装，48 个平台适用依赖已安装；锁文件共解析 52 个跨平台依赖条目。
- 依赖一致性：`uv lock --check --offline` 成功。
- 自动化测试：`.venv/bin/python -m pytest -q`，**14 passed in 1.49s**。
- SDK 离线测试：使用实际安装的 Agent/Runner 与本地 HTTP mock，确认仅一次 Chat Completions 请求、模型参数、thinking 禁用、输出 token 上限及 token 用量解析。该测试中的响应和 token 数均为测试夹具，不是真实 Provider 数据。
- 真实 HTTP 健康检查：临时 Uvicorn 绑定 `127.0.0.1:8000`，GET `/api/health` 返回 HTTP 200 和 `{"status":"ok","stage":"0","scope":"process"}`。验证后自动停止服务，未留下常驻进程。
- 模型真实调用：初次运行因缺少密钥返回 `configuration_error`、退出码 **2**。2026-10-22 用户完成本地配置并执行 `.venv/bin/python -m scripts.smoke_model`，提供成功输出：`{"status":"ok","provider":"deepseek","protocol":"chat_completions","model":"deepseek-flash","requests":1,"input_tokens":28,"output_tokens":5}`。此为用户提供的本机实测结果，Agent 未重复发起付费请求。
- 安全配置：创建时本地 `.env` 权限已确认 `-rw-------`，密钥字段当时留空；后续由用户本地配置，Agent 未读取或展示密钥；原规范未覆盖。
- 未解决：阶段 0 无阻塞项；Intel 实机兼容性和 Docker 守护进程状态仍未经验证，均不影响本次本机部署验收。
- 是否满足验收：**满足阶段 0 验收**；基础环境、锁定依赖、14 项自动化测试、真实 HTTP 健康检查和用户提供的真实模型调用均已通过。
- 下一步：按规范等待用户指令进入阶段 1，不自动展开完整系统开发。

安装时第一次下载在代理链路上超时。最终用以下命令绕过代理成功（只影响该命令，不修改系统代理配置）：

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy UV_CACHE_DIR="$PWD/.cache/uv" UV_HTTP_TIMEOUT=120 UV_CONCURRENT_DOWNLOADS=3 uv sync --locked --python /Users/tyu/anaconda3/bin/python3.11
```

系统 Python 的首次字节码检查受系统缓存目录写入权限限制；改用项目缓存路径后语法检查通过。该问题不影响项目 Python 的测试和运行。

## 官方依据

- [Agents SDK 安装与 Runner 示例](https://developers.openai.com/api/docs/guides/agents/quickstart?lang=python)
- [模型与 Provider 配置](https://developers.openai.com/api/docs/guides/agents/models)
- [规范指定的 Python SDK 仓库与许可证](https://github.com/openai/openai-agents-python)
- [openai-agents PyPI 元数据](https://pypi.org/pypi/openai-agents/json)
- [DeepSeek 首次 API 调用和模型名称](https://api-docs.deepseek.com/)
