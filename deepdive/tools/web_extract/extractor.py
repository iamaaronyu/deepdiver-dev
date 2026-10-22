"""Fetch bounded HTML with DNS pinning, original TLS SNI, and manual redirect checks."""
import asyncio
import hashlib
from urllib.parse import urljoin

import httpx
import trafilatura
from lxml import html as lxml_html

from deepdive.evidence.sources import Source, timestamp
from deepdive.tools.search.models import ToolFailure
from deepdive.tools.web_extract.security import normalize_url, resolve_public

MAX_PAGE_BYTES = 2 * 1024 * 1024


class WebExtractor:
    def __init__(self, *, timeout=20, resolver=resolve_public, transport_factory=None):
        self.timeout = timeout
        self.resolver = resolver
        self.transport_factory = transport_factory

    async def _page(self, url):
        # A fresh transport per hop prevents TLS connections being reused across hostnames sharing an IP.
        target = httpx.URL(url)
        address = await self.resolver(target.host, target.port or (443 if target.scheme == "https" else 80))
        transport = self.transport_factory() if self.transport_factory else httpx.AsyncHTTPTransport(retries=0)
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=self.timeout) as client:
            async with client.stream("GET", target.copy_with(host=address),
                headers={"Host": target.netloc.decode("ascii"), "User-Agent": "DeepDiveLocal/0.2", "Accept-Encoding": "identity"},
                extensions={"sni_hostname": target.host}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise ToolFailure("invalid_redirect", "来源重定向缺少目标。")
                    return None, normalize_url(urljoin(url, location)), None
                if response.status_code >= 500:
                    raise httpx.ConnectError("transient upstream failure")
                if response.status_code != 200:
                    raise ToolFailure("fetch_http_error", "来源页面返回非成功状态。")
                content_type = response.headers.get("content-type", "").split(";")[0].lower().strip()
                if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    raise ToolFailure("unsupported_content", "来源不是支持的 HTML 或纯文本页面。")
                if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                    raise ToolFailure("unsupported_encoding", "来源未遵守 identity 内容编码请求。")
                chunks = bytearray()
                async for chunk in response.aiter_raw():
                    if len(chunks) + len(chunk) > MAX_PAGE_BYTES:
                        raise ToolFailure("page_too_large", "来源页面超过 2 MiB。")
                    chunks.extend(chunk)
                return bytes(chunks), None, content_type

    async def fetch(self, url: str, title="") -> Source:
        source = Source.pending(url, title)
        try:
            async with asyncio.timeout(self.timeout):
                current = normalize_url(url)
                source.canonical_url = current
                for attempt in range(2):
                    source.attempts = attempt + 1
                    try:
                        for hop in range(6):
                            page, redirect, content_type = await self._page(current)
                            if redirect is None:
                                break
                            if hop == 5:
                                raise ToolFailure("too_many_redirects", "来源重定向次数超过限制。")
                            current = redirect
                            source.canonical_url = current
                        source.canonical_url = current
                        if content_type == "text/plain":
                            text, metadata = page.decode("utf-8", errors="replace").strip(), {}
                        else:
                            text, metadata = await asyncio.to_thread(extract_html, page, current)
                        if len(text.strip()) < 80:
                            raise ToolFailure("empty_extraction", "来源正文不足，不能作为有效来源。")
                        source.extracted_text = text[:50000]
                        source.truncated = len(text) > 50000
                        source.content_hash = hashlib.sha256(source.extracted_text.encode()).hexdigest()
                        source.title = str(metadata.get("title") or title or httpx.URL(current).host)[:1000]
                        source.author = metadata.get("author")
                        source.publisher = metadata.get("sitename")
                        source.published_at = metadata.get("explicit_date")
                        source.retrieved_at = timestamp()
                        source.redirect_chain_verified = True
                        source.fetch_status = "FETCHED"
                        return source
                    except (httpx.TimeoutException, httpx.NetworkError):
                        if attempt:
                            raise
                        await asyncio.sleep(0.2)
        except (TimeoutError, httpx.TimeoutException):
            source.error_code = "fetch_timeout"
        except ToolFailure as exc:
            source.error_code = exc.code
        except httpx.NetworkError:
            source.error_code = "fetch_network_error"
        except Exception:
            source.error_code = "extraction_failed"
        return source


def extract_html(page: bytes, url: str):
    # No fetch_url or crawler: extraction only consumes already fetched bytes.
    document = trafilatura.bare_extraction(page, url=url, with_metadata=True, include_comments=False,
                                         include_links=False, fast=True)
    if not document:
        return "", {}
    document = document.as_dict()
    tree = lxml_html.fromstring(page)
    dates = tree.xpath('//meta[@property="article:published_time" or @name="datePublished"]/@content')
    document["explicit_date"] = str(dates[0])[:100] if dates else None
    return str(document.get("text") or ""), document
