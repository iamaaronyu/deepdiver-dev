from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolFailure(Exception):
    code: str
    message: str
    http_status: int = 502
    requests: int = 0


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str = ""
    publisher: str | None = None
    published_at: str | None = None


@dataclass
class SearchResults:
    hits: list[SearchHit]
    requests: int
    provider_usage: dict = field(default_factory=dict)


class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int = 10) -> SearchResults: ...
