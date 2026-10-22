from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


def timestamp():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Source:
    id: str
    url: str
    canonical_url: str
    title: str
    retrieved_at: str
    fetch_status: str = "FAILED"
    author: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    content_hash: str | None = None
    extracted_text: str = ""
    attempts: int = 0
    error_code: str | None = None
    duplicate_of: str | None = None
    truncated: bool = False
    fetch_provider: str = "local_http"
    redirect_chain_verified: bool = False
    fetch_requests: int = 0
    fetch_successes: int = 0

    @classmethod
    def pending(cls, url, title=""):
        return cls(uuid4().hex, url, "", title, timestamp())
