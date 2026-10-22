from pydantic import BaseModel, ConfigDict, Field


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=128)
    max_results: int = Field(default=10, ge=1, le=10, strict=True)


class SourceSummary(BaseModel):
    id: str
    url: str
    canonical_url: str
    title: str
    retrieved_at: str
    fetch_status: str
    author: str | None
    publisher: str | None
    published_at: str | None
    content_hash: str | None
    attempts: int
    error_code: str | None
    duplicate_of: str | None
    truncated: bool
    fetch_provider: str
    redirect_chain_verified: bool
    fetch_requests: int
    fetch_successes: int
    excerpt: str


class SourceResponse(BaseModel):
    request_id: str
    id: str
    question: str
    created_at: str
    completed_at: str
    status: str
    search_requests: int
    provider_usage: dict
    valid_sources: int
    sources: list[SourceSummary]
    error_code: str | None = None
