import asyncio
from dataclasses import asdict
from uuid import uuid4

from deepdive.evidence.repository import SourceRepository
from deepdive.evidence.sources import Source, timestamp
from deepdive.tools.search.models import SearchProvider, ToolFailure
from deepdive.tools.web_extract.extractor import WebExtractor
from deepdive.tools.web_extract.security import normalize_url


class SourceCollector:
    def __init__(self, provider: SearchProvider, extractor=None, repository=None):
        self.provider = provider
        self.extractor = extractor or WebExtractor()
        self.repository = repository or SourceRepository()
        self._slot = asyncio.Semaphore(1)

    async def collect(self, question: str, max_results=10):
        collection = {"id": uuid4().hex, "question": question, "created_at": timestamp(), "status": "RUNNING",
                      "search_requests": 0, "provider_usage": {}, "sources": [], "valid_sources": 0}
        try:
            async with asyncio.timeout(150):
                async with self._slot:
                    results = await self.provider.search(question, max_results)
                    collection["search_requests"] = results.requests
                    collection["provider_usage"] = results.provider_usage
                    source_slots = []
                    urls = {}
                    jobs = []
                    semaphore = asyncio.Semaphore(5)

                    async def fetch(hit, index):
                        try:
                            async with semaphore:
                                source = await self.extractor.fetch(hit.url, hit.title)
                                source.id = source_slots[index].id
                                source.publisher = source.publisher or hit.publisher
                                source.published_at = source.published_at or hit.published_at
                                source_slots[index] = source
                        except asyncio.CancelledError:
                            source_slots[index].fetch_status = "CANCELLED"
                            source_slots[index].error_code = "fetch_cancelled"
                            raise

                    for hit in results.hits[:max_results]:
                        try:
                            canonical = normalize_url(hit.url)
                        except ToolFailure as exc:
                            source = Source.pending(hit.url, hit.title)
                            source.error_code = exc.code
                            source_slots.append(source)
                            continue
                        if canonical in urls:
                            source = Source.pending(hit.url, hit.title)
                            source.canonical_url = canonical
                            source.fetch_status = "DUPLICATE_URL"
                            source.duplicate_of = source_slots[urls[canonical]].id
                            source_slots.append(source)
                            continue
                        urls[canonical] = len(source_slots)
                        pending = Source.pending(hit.url, hit.title)
                        pending.fetch_status = "PENDING"
                        source_slots.append(pending)
                        jobs.append(fetch(hit, len(source_slots) - 1))
                    try:
                        await asyncio.gather(*jobs)
                    finally:
                        # Progress material is preserved even if a task-wide deadline cancels a fetch.
                        for index, source in enumerate(source_slots):
                            if source is not None:
                                collection["sources"].append(asdict(source))
                    hashes = {}
                    final_urls = {}
                    for source in source_slots:
                        if source.fetch_status == "FETCHED":
                            duplicate = final_urls.get(source.canonical_url) or hashes.get(source.content_hash)
                            if duplicate:
                                source.fetch_status = "DUPLICATE_CONTENT"
                                source.duplicate_of = duplicate
                                source.extracted_text = ""
                            else:
                                hashes[source.content_hash] = source.id
                                final_urls[source.canonical_url] = source.id
                    collection["sources"] = [asdict(source) for source in source_slots]
                    collection["valid_sources"] = sum(source.fetch_status == "FETCHED" for source in source_slots)
                    collection["status"] = "COMPLETED" if collection["valid_sources"] else "NO_VALID_SOURCES"
        except TimeoutError:
            collection["status"] = "TIMED_OUT"
            collection["error_code"] = "collection_timeout"
        except ToolFailure as exc:
            collection["status"] = "FAILED"
            collection["search_requests"] = exc.requests
            collection["error_code"] = exc.code
            raise
        except asyncio.CancelledError:
            collection["status"] = "CANCELLED"
            raise
        except Exception:
            collection["status"] = "FAILED"
            collection["error_code"] = "collection_failed"
            raise ToolFailure("collection_failed", "来源采集失败。") from None
        finally:
            collection["valid_sources"] = sum(source["fetch_status"] == "FETCHED" for source in collection["sources"])
            collection["provider_usage"]["fetch_requests"] = sum(source.get("fetch_requests", 0) for source in collection["sources"])
            collection["provider_usage"]["fetch_successes"] = sum(source.get("fetch_successes", 0) for source in collection["sources"])
            collection["provider_usage"]["fetch_request_count_complete"] = not any(source["fetch_status"] == "CANCELLED" for source in collection["sources"])
            collection["completed_at"] = timestamp()
            try:
                self.repository.save(collection)
            except OSError:
                raise ToolFailure("source_storage_failed", "来源记录保存失败，请检查本地磁盘与权限。") from None
        return collection


def summarize(collection):
    return {**collection, "sources": [{key: value for key, value in source.items() if key != "extracted_text"}
                                      | {"excerpt": source["extracted_text"][:1000]} for source in collection["sources"]]}
