# 阶段 2：搜索与网页提取（DeepSeek）

日期：2026-10-22（Asia/Shanghai）。用户明确选择 DeepSeek Search / Fetch API；默认路径已从初版 Tavily 改为 DeepSeek，复用本地已有 DEEPSEEK_API_KEY，不再要求配置 Tavily 密钥。此阶段不进入完整研究闭环或 Web UI。

## 已完成

- 默认调用独立的 `POST https://api.deepseek.com/v1/tools/search`，参数 query/count/need_content；query 严格限制 1–128 Unicode 字符，本地结果数限制 1–10。
- 对实际搜索结果 URL 调用 `/v1/tools/fetch` 获取 Markdown。搜索 snippet / summary 不作为 Fetch 正文，不通过聊天模型模拟联网。
- Provider 协议与业务编排分离；保留显式 `SEARCH_PROVIDER=tavily` 的备选路径，但默认值为 deepseek。
- 搜索/Fetch 最多一次重试，处理认证失败、余额不足、安全拒绝、页面不可用、限流、网络与超时；固定错误码，不转发上游正文或密钥。
- 记录搜索请求尝试次数、Fetch 尝试次数和成功内容响应数；不虚构 token 或成本。取消导致用量可能不完整时显式标记。
- URL 和 SHA-256 内容双重去重；来源保留 URL、标题、抓取时间、正文、可得出版方及搜索服务报告的日期、哈希、截断标记、失败/重复状态及关联 ID。未知作者/日期不猜测。
- 原子 JSON 记录存入 `data/sources`，默认文件权限 600、目录创建权限 700，已被 Git 忽略；API 返回最长 1000 字符摘录，完整正文最多 50000 字符。
- 同时最多 5 个 Fetch，一个进程同时一个集合；集合截止时间 150 秒包含排队，单个 Fetch 20 秒包含本地目标检查和工具 API 请求；API 响应读取上限 2 MiB。
- `POST /api/sources` 提供稳定请求/响应 Schema，`GET /api/health` 显示配置状态，首页跳转到健康接口。

## 安全边界

DeepSeek Fetch 提交前，本地拒绝不安全协议、端口、URL 用户信息以及解析到本机/私网/元数据/特殊/IPv6 转换地址的目标；工具请求仅发送到固定官方 HTTPS 端点。工具响应和网页正文作为不可信数据保存，不执行其中的脚本、技能或命令。

**远端 Fetch 的 DNS 解析和重定向由供应商控制，官方响应只包含 title/content，不包含最终 URL 或重定向链。** 因此明确记录 `fetch_provider=deepseek_fetch`、`redirect_chain_verified=false`；canonical_url 仅为请求 URL 的规范化版本，不能声称本地核验了全部跳转或来源内容真实性。发布时间来自搜索服务实际返回的 date，不能视为独立核验。

保留的 Tavily + 本地 HTTPX/Trafilatura 路径则逐跳检查全部 DNS 地址、固定实际公网连接 IP、保留原 Host/TLS SNI 和证书校验，并为每一跳新建传输；成功时 redirect_chain_verified=true。两种路径的 FETCHED 都只表示取得正文，不表示主张已核实。

## 文件与版本

- 新增 `deepdive/providers/deepseek_tools.py`、`registry.py`：官方 Search/Fetch HTTP 适配器与默认供应商选择。
- `deepdive/providers/search.py`：保留 Tavily 备选适配器。
- `deepdive/tools/search/models.py`、`collect.py`：统一协议、采集、去重、统计、超时保留材料。
- `deepdive/tools/web_extract/security.py`、`extractor.py`：目标校验和保留的本地安全抓取路径。
- `deepdive/evidence/sources.py`、`repository.py`：来源模型与原子存储。
- `apps/api/main.py`、`apps/api/schemas/sources.py`：默认 DeepSeek 选择、来源接口和当前 Schema。
- `scripts/smoke_search.py`：真实采集验收入口，只有至少 5 个有效来源才退出 0。
- `tests/test_stage2.py`、`test_deepseek_tools.py`、`conftest.py`：离线测试与真实凭证隔离。
- `.env.example`、`README.md`：默认 SEARCH_PROVIDER=deepseek，模型与搜索复用 DEEPSEEK_API_KEY；未覆盖用户 .env。
- `pyproject.toml`、`uv.lock`：项目版本 0.2.1；运行依赖 HTTPX 0.28.1 和 Trafilatura 2.3.1 已锁定。切换 DeepSeek 未增加第三方依赖。

## 测试与真实结果

```sh
.venv/bin/python -m pytest -q
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked --offline
.venv/bin/python -m scripts.smoke_search "site:docs.python.org asyncio tasks queues streams subprocess synchronization"
```

- 全部自动化测试：**89 passed in 2.29s**，无警告。覆盖官方请求 Schema、默认密钥复用、128 字符限制、错误脱敏与重试、远端 Fetch 安全边界、超时用量计数，以及原有阶段 0–2 测试。
- 离线锁文件同步成功，检查 63 个平台适用依赖。
- 已重启并保持本机 API 运行，仅监听 `127.0.0.1:8000`。真实 HTTP 首页跳转后返回 200：`stage=2`、`model_configured=true`、`search_configured=true`；OpenAPI 版本 0.2.1；129 字符搜索问题返回 422，未调用供应商。

真实 Search/Fetch 记录（保留全部尝试，不以修改结果制造通过）：

| 查询 | 有效正文来源 | 搜索尝试 | Fetch 成功内容响应 | CLI 退出码 | 记录 ID |
| --- | --- | --- | --- | --- | --- |
| 循证研究方法：如何评估来源可靠性与交叉验证证据？ | 3 | 1 | 3 | 1 | d87c4cd51de44ae2a200d67bbb2f77d2 |
| Python asyncio TaskGroup cancellation and concurrency tutorial | 4 | 1 | 5，其中 1 个正文不足 80 字符 | 1 | 858b6857e1e546eaac54e5f9c6798a58 |
| site:docs.python.org asyncio tasks queues streams subprocess synchronization | **7** | **1** | **7** | **0** | **28b94f95d1be4a1a83ecfdf4a4aebd8d** |

第三轮 Fetch 尝试 10 次，7 个正文有效；实际 JSON 文件验证了 7 个不同规范化 URL、7 个不同正文哈希、非空标题/正文/抓取时间，且明确标记供应商抓取、跳转链未本地验证。文件位置 `data/sources/<记录ID>.json`。

首轮旧版本在 Fetch 总超时路径可能少计请求尝试次数，已在该原始记录注明 fetch_request_count_complete=false 并保留原结果；随后修复并增加超时计数回归测试。第三轮请求计数完整。Fetch 失败、超时和短正文均未冒充有效来源。

初版本地抓取路径另实测 Example Domain（156 字符）和 PyPI Trafilatura 页面（8451 字符）成功，Python 官网介绍页超时；这些定向抓取未计入上述搜索验收。

## 验收与下一步

**满足阶段 2 验收**：实际一个问题检索并取得 7 个不重复有效正文来源，达到至少 5 个来源门槛；来源包含实际 URL、抓取时间、标题、正文及哈希；搜索失败、网页超时与重复来源均有测试。

已知限制：某些搜索结果对应 PDF、验证码、失效页或不可提取页面，Fetch 仍可能失败；成功获取不等于内容可靠。远端重定向不可独立确认，事实支持度和来源独立性由阶段 3 Verifier 进一步处理。当前没有完整研究报告、历史任务 UI 或远程认证。

下一步按原规范等待进入阶段 3：显式研究状态机、预算、Planner/Researcher/Verifier/Writer、关系型证据存储和引用报告。

## 官方依据

- [DeepSeek Search / Fetch 指南与计费](https://api-docs.deepseek.com/guides/search/)
- [Search API Schema](https://api-docs.deepseek.com/api/search/)
- [Fetch API Schema](https://api-docs.deepseek.com/api/fetch/)
- [Trafilatura](https://trafilatura.readthedocs.io/en/latest/corefunctions.html)
- [HTTPX 自定义传输](https://www.python-httpx.org/advanced/transports/)
