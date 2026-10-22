"""Tavily REST adapter. No LLM answers or provider raw pages are accepted as fetched evidence."""
import asyncio
import json
from dataclasses import dataclass, field
import os

import httpx
from dotenv import load_dotenv

from deepdive.config import ConfigurationError, ROOT
from deepdive.tools.search.models import SearchHit, SearchResults, ToolFailure


@dataclass(frozen=True)
class SearchConfig:
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        key = os.getenv("TAVILY_API_KEY", "").strip()
        if not key or key in {"replace-me", "your-api-key"}:
            raise ConfigurationError("TAVILY_API_KEY is not configured.")
        return cls(key)


class TavilySearch:
    def __init__(self, config: SearchConfig, *, transport=None):
        self.config = config
        self.transport = transport

    async def search(self, query: str, max_results: int = 10) -> SearchResults:
        if not 1 <= len(query.strip()) <= 2000 or not 1 <= max_results <= 10:
            raise ToolFailure("invalid_search_request", "搜索问题或来源数不合法。", 422)
        requests = 0
        try:
            async with asyncio.timeout(35):
                async with httpx.AsyncClient(timeout=15, trust_env=False, transport=self.transport) as client:
                    for attempt in range(2):
                        requests += 1
                        try:
                            async with client.stream("POST", "https://api.tavily.com/search",
                                headers={"Authorization": "Bearer " + self.config.api_key},
                                json={"query": query, "max_results": max_results, "search_depth": "basic",
                                      "auto_parameters": False, "include_answer": False, "include_raw_content": False,
                                      "include_images": False, "include_usage": True}) as response:
                                if response.status_code in (401, 403):
                                    raise ToolFailure("search_authentication_failed", "搜索服务认证失败，请检查本地密钥。")
                                if response.status_code in (429, 432, 433):
                                    raise ToolFailure("search_rate_limited", "搜索服务限流或额度不足。", 503)
                                if response.status_code >= 500 and attempt == 0:
                                    await asyncio.sleep(0.2)
                                    continue
                                response.raise_for_status()
                                body = bytearray()
                                async for chunk in response.aiter_bytes():
                                    body.extend(chunk)
                                    if len(body) > 1_000_000:
                                        raise ToolFailure("search_response_too_large", "搜索响应超过大小限制。")
                            data = json.loads(body)
                            items = data["results"]
                            if not isinstance(items, list):
                                raise ValueError()
                            hits = []
                            for item in items[:max_results]:
                                if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                                    raise ValueError()
                                hits.append(SearchHit(item["url"], str(item.get("title") or "")[:1000], str(item.get("content") or "")[:3000]))
                            usage = data.get("usage", {})
                            credits = usage.get("credits") if isinstance(usage, dict) else None
                            safe_usage = {"credits": credits} if type(credits) in (int, float) and 0 <= credits < 1000 else {}
                            return SearchResults(hits, requests, safe_usage)
                        except (httpx.TimeoutException, httpx.NetworkError):
                            if attempt:
                                raise
                            await asyncio.sleep(0.2)
        except ToolFailure as exc:
            exc.requests = requests
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise ToolFailure("search_timeout", "搜索服务请求超时。", 504, requests=requests) from None
        except httpx.NetworkError:
            raise ToolFailure("search_unreachable", "无法连接搜索服务。", requests=requests) from None
        except Exception:
            raise ToolFailure("search_provider_error", "搜索服务返回无效结果或请求失败。", requests=requests) from None
        raise ToolFailure("search_provider_error", "搜索服务未返回结果。")
