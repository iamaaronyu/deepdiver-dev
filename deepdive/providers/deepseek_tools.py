"""DeepSeek raw Search/Fetch APIs, separate from chat model calls."""
import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv

from deepdive.config import ConfigurationError, ROOT
from deepdive.evidence.sources import Source, timestamp
from deepdive.tools.search.models import SearchHit, SearchResults, ToolFailure
from deepdive.tools.web_extract.security import normalize_url, resolve_public


@dataclass(frozen=True)
class DeepSeekToolsConfig:
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not key or key in {"replace-me", "your-api-key"}:
            raise ConfigurationError("DEEPSEEK_API_KEY is not configured.")
        return cls(key)


class DeepSeekTools:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.transport = transport

    async def post(self, tool, payload, timeout, on_attempt=None):
        attempts = 0
        try:
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(timeout=timeout, trust_env=False, transport=self.transport, follow_redirects=False) as client:
                    for attempt in range(2):
                        attempts += 1
                        if on_attempt is not None:
                            on_attempt(attempts)
                        try:
                            async with client.stream("POST", "https://api.deepseek.com/v1/tools/" + tool,
                                headers={"Authorization": "Bearer " + self.config.api_key}, json=payload) as response:
                                if response.status_code in (408, 429, 500, 502, 503, 504) and attempt == 0:
                                    await asyncio.sleep(0.2)
                                    continue
                                errors = {
                                    401: ("tools_authentication_failed", "DeepSeek 工具认证失败。", 502),
                                    402: ("tools_insufficient_balance", "DeepSeek 账户余额不足。", 503),
                                    403: ("tools_security_rejected", "DeepSeek 工具安全策略拒绝请求。", 502),
                                    404: ("tools_content_unavailable", "DeepSeek 工具无法获取页面或接口不可用。", 502),
                                    429: ("tools_rate_limited", "DeepSeek 工具限流。", 503),
                                    504: ("tools_timeout", "DeepSeek 工具请求超时。", 504),
                                }
                                if response.status_code in errors:
                                    raise ToolFailure(*errors[response.status_code], requests=attempts)
                                response.raise_for_status()
                                body = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(body) + len(chunk) > 2 * 1024 * 1024:
                                        raise ToolFailure("tools_response_too_large", "DeepSeek 工具响应超过 2 MiB。")
                                    body.extend(chunk)
                            data = json.loads(body)
                            if not isinstance(data, dict):
                                raise ValueError()
                            return data, attempts
                        except (httpx.TimeoutException, httpx.NetworkError):
                            if attempt:
                                raise
                            await asyncio.sleep(0.2)
        except ToolFailure as exc:
            exc.requests = attempts
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise ToolFailure("tools_timeout", "DeepSeek 工具请求超时。", 504, requests=attempts) from None
        except httpx.NetworkError:
            raise ToolFailure("tools_unreachable", "无法连接 DeepSeek 工具服务。", requests=attempts) from None
        except Exception:
            raise ToolFailure("tools_provider_error", "DeepSeek 工具返回无效结果或请求失败。", requests=attempts) from None
        raise ToolFailure("tools_provider_error", "DeepSeek 工具未返回结果。", requests=attempts)


class DeepSeekSearch:
    def __init__(self, config, *, transport=None):
        self.tools = DeepSeekTools(config, transport=transport)

    async def search(self, query, max_results=10):
        if not 1 <= len(query.strip()) <= 128 or not 1 <= max_results <= 10:
            raise ToolFailure("invalid_search_request", "DeepSeek 搜索 query 必须为 1–128 字符，结果数为 1–10。", 422)
        data, attempts = await self.tools.post("search", {"query": query, "count": max_results, "need_content": False}, 35)
        items = data.get("results")
        if not isinstance(items, list) or any(not isinstance(item, dict) or not isinstance(item.get("url"), str) for item in items):
            raise ToolFailure("tools_provider_error", "DeepSeek 搜索响应格式不合法。", requests=attempts)
        hits = [SearchHit(item["url"], str(item.get("title") or "")[:1000], str(item.get("snippet") or "")[:3000],
                          publisher=str(item["site_name"])[:1000] if item.get("site_name") else None,
                          published_at=str(item["date"])[:100] if item.get("date") else None) for item in items[:max_results]]
        return SearchResults(hits, attempts, {"provider": "deepseek", "search_successes": int(bool(items))})


class DeepSeekFetch:
    def __init__(self, config, *, transport=None, resolver=resolve_public, timeout=20):
        self.tools = DeepSeekTools(config, transport=transport)
        self.resolver = resolver
        self.timeout = timeout

    async def fetch(self, url, title=""):
        source = Source.pending(url, title)
        source.fetch_provider = "deepseek_fetch"
        try:
            async with asyncio.timeout(self.timeout):
                canonical = normalize_url(url)
                source.canonical_url = canonical
                target = httpx.URL(canonical)
                # Only the submitted target can be checked locally. Provider redirects are not exposed.
                await self.resolver(target.host, target.port or (443 if target.scheme == "https" else 80))
                def mark_attempt(number):
                    source.fetch_requests = source.attempts = number
                data, requests = await self.tools.post("fetch", {"url": canonical}, self.timeout, on_attempt=mark_attempt)
                source.fetch_requests = source.attempts = requests
                content = data.get("content")
                if not isinstance(content, str):
                    raise ToolFailure("tools_provider_error", "DeepSeek Fetch 响应格式不合法。")
                source.fetch_successes = int(bool(content.strip()))
                if len(content.strip()) < 80:
                    raise ToolFailure("empty_extraction", "DeepSeek Fetch 正文不足，不能作为有效来源。")
                content = content.replace(self.tools.config.api_key, "[REDACTED]")
                source.title = str(data.get("title") or title or target.host).replace(self.tools.config.api_key, "[REDACTED]")[:1000]
                source.extracted_text = content[:50000]
                source.truncated = len(content) > 50000
                source.content_hash = hashlib.sha256(source.extracted_text.encode()).hexdigest()
                source.retrieved_at = timestamp()
                source.fetch_status = "FETCHED"
        except ToolFailure as exc:
            source.error_code = exc.code
            source.fetch_requests = source.attempts = max(source.fetch_requests, exc.requests)
        except TimeoutError:
            source.error_code = "tools_timeout"
        except Exception:
            source.error_code = "tools_fetch_failed"
        return source
