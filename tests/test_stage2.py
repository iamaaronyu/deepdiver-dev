import asyncio
import hashlib
import json
import socket
from dataclasses import asdict

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from deepdive.evidence.repository import SourceRepository
from deepdive.evidence.sources import Source
from deepdive.providers.search import SearchConfig, TavilySearch
from deepdive.tools.search.collect import SourceCollector
from deepdive.tools.search.models import SearchHit, SearchResults, ToolFailure
from deepdive.tools.web_extract.extractor import WebExtractor, MAX_PAGE_BYTES
from deepdive.tools.web_extract.security import normalize_url, public_address, resolve_public

HTML = ('<html><head><title>Research methods</title><meta name="author" content="Test Author">'
        '<meta property="article:published_time" content="2026-10-01"></head><body><article><h1>Research methods</h1>'
        + '<p>Evidence based research requires comparing independent sources, recording their origin and reviewing limitations.</p>' * 8
        + '</article></body></html>').encode()


async def public_dns(host, port):
    return "93.184.216.34"


def extractor(handler, **kwargs):
    return WebExtractor(resolver=public_dns, transport_factory=lambda: httpx.MockTransport(handler), **kwargs)


def html_response(body=HTML, **kwargs):
    return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(body), **kwargs)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/a", "http://localhost/", "https://test.local/", "https://user:secret@example.com/", "https://example.com:8000/", "https://example.com\\@127.0.0.1/", "http://example.com/\nfoo"])
def test_unsafe_url(url):
    with pytest.raises(ToolFailure):
        normalize_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "100.64.0.1", "0.0.0.0", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::", "224.0.0.1", "ff02::1"])
def test_private_and_transition_addresses_rejected(address):
    assert not public_address(address)


def test_url_normalization():
    assert normalize_url('https://EXAMPLE.com:443/a?utm_source=x&id=2#section') == 'https://example.com/a?id=2'
    assert normalize_url('https://example.com/a?id=2') != normalize_url('https://example.com/a?id=3')


def test_mixed_dns_answer_rejected(monkeypatch):
    async def scenario():
        async def dns(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', dns)
        with pytest.raises(ToolFailure, match='unsafe_address'):
            await resolve_public('example.com', 443)
    asyncio.run(scenario())


def test_fetch_is_pinned_and_preserves_sni_and_metadata():
    seen = []
    def handle(request):
        seen.append(request)
        assert request.url.host == '93.184.216.34'
        assert request.headers['host'] == 'example.com'
        assert request.extensions['sni_hostname'] == 'example.com'
        assert 'authorization' not in request.headers
        return html_response()
    source = asyncio.run(extractor(handle).fetch('https://example.com/article'))
    assert len(seen) == 1
    assert source.fetch_status == 'FETCHED'
    assert source.content_hash == hashlib.sha256(source.extracted_text.encode()).hexdigest()
    assert source.published_at == '2026-10-01'
    assert source.title == 'Research methods'
    assert source.retrieved_at


def test_unknown_date_not_inferred():
    body = HTML.replace(b'<meta property="article:published_time" content="2026-10-01">', b'')
    source = asyncio.run(extractor(lambda request: html_response(body)).fetch('https://example.com/2026/10/01/article'))
    assert source.fetch_status == 'FETCHED'
    assert source.published_at is None


def test_redirect_to_private_address_is_blocked():
    seen = []
    async def dns(host, port):
        return await resolve_public(host, port) if host == '127.0.0.1' else '93.184.216.34'
    def handle(request):
        seen.append(request)
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/admin'})
    fetcher = WebExtractor(resolver=dns, transport_factory=lambda: httpx.MockTransport(handle))
    source = asyncio.run(fetcher.fetch('https://example.com/start'))
    assert source.fetch_status == 'FAILED'
    assert source.error_code == 'unsafe_address'
    assert len(seen) == 1


def test_redirect_dns_checked_again_before_connection():
    names = []
    async def dns(host, port):
        names.append(host)
        if len(names) > 1:
            raise ToolFailure('unsafe_address', 'blocked')
        return '93.184.216.34'
    fetcher = WebExtractor(resolver=dns, transport_factory=lambda: httpx.MockTransport(lambda request: httpx.Response(302, headers={'location': '/other'})))
    source = asyncio.run(fetcher.fetch('https://example.com/'))
    assert source.error_code == 'unsafe_address'
    assert names == ['example.com', 'example.com']


def test_fetch_timeout_has_bounded_retry():
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout('secret upstream error')
    source = asyncio.run(extractor(handle).fetch('https://example.com/'))
    assert source.error_code == 'fetch_timeout'
    assert source.attempts == len(calls) == 2


def test_total_fetch_deadline_includes_dns():
    async def slow_dns(*args):
        await asyncio.sleep(1)
        return '93.184.216.34'
    source = asyncio.run(WebExtractor(timeout=0.01, resolver=slow_dns).fetch('https://example.com/'))
    assert source.error_code == 'fetch_timeout'


@pytest.mark.parametrize('response,error', [
    (lambda: html_response(b'x' * (MAX_PAGE_BYTES + 1)), 'page_too_large'),
    (lambda: httpx.Response(200, headers={'content-type': 'application/pdf'}, stream=httpx.ByteStream(b'pdf')), 'unsupported_content'),
    (lambda: httpx.Response(200, headers={'content-type': 'text/html', 'content-encoding': 'gzip'}, stream=httpx.ByteStream(b'bad')), 'unsupported_encoding'),
    (lambda: httpx.Response(404), 'fetch_http_error'),
    (lambda: html_response(b'<p>short</p>'), 'empty_extraction'),
])
def test_invalid_pages_are_not_valid_sources(response, error):
    source = asyncio.run(extractor(lambda request: response()).fetch('https://example.com/'))
    assert source.fetch_status == 'FAILED'
    assert source.error_code == error


def test_search_adapter_does_not_request_generated_answers():
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers['authorization'] == 'Bearer test-key'
        payload = json.loads(request.content)
        assert payload['include_answer'] is False
        assert payload['include_raw_content'] is False
        assert payload['search_depth'] == 'basic'
        return httpx.Response(200, json={'results': [{'url':'https://example.com/', 'title':'Title', 'content':'Snippet'}], 'usage': {'credits': 1, 'untrusted': 'not forwarded'}})
    result = asyncio.run(TavilySearch(SearchConfig('test-key'), transport=httpx.MockTransport(handle)).search('question'))
    assert result.requests == len(calls) == 1
    assert result.provider_usage == {'credits': 1}
    assert result.hits[0].url == 'https://example.com/'
    assert 'test-key' not in repr(SearchConfig('test-key'))


@pytest.mark.parametrize('status,code,count', [(401,'search_authentication_failed',1), (429,'search_rate_limited',1), (500,'search_provider_error',2)])
def test_search_failure_sanitized_and_retries_bounded(status, code, count):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'error':'secret-test-key'})
    with pytest.raises(ToolFailure) as caught:
        asyncio.run(TavilySearch(SearchConfig('secret-test-key'), transport=httpx.MockTransport(handle)).search('question'))
    assert caught.value.code == code
    assert 'secret-test-key' not in str(caught.value)
    assert len(calls) == count


def test_source_collection_deduplicates_and_persists(tmp_path):
    class Provider:
        async def search(self, question, max_results):
            return SearchResults([SearchHit('https://example.com/a','A'), SearchHit('https://EXAMPLE.com/a?utm_source=test','A2'), SearchHit('https://example.com/b','B')], 1)
    calls = []
    def handle(request):
        calls.append(request)
        return html_response()
    collector = SourceCollector(Provider(), extractor(handle), SourceRepository(tmp_path))
    result = asyncio.run(collector.collect('question'))
    assert len(calls) == 2
    assert result['valid_sources'] == 1
    assert [s['fetch_status'] for s in result['sources']] == ['FETCHED','DUPLICATE_URL','DUPLICATE_CONTENT']
    assert result['sources'][1]['duplicate_of'] == result['sources'][0]['id']
    assert result['sources'][2]['duplicate_of'] == result['sources'][0]['id']
    stored = json.loads((tmp_path / (result['id'] + '.json')).read_text())
    assert stored == result
    assert stored['sources'][0]['extracted_text']


def test_search_failure_saved(tmp_path):
    class Provider:
        async def search(self, question, max_results):
            raise ToolFailure('search_authentication_failed','safe')
    with pytest.raises(ToolFailure):
        asyncio.run(SourceCollector(Provider(), repository=SourceRepository(tmp_path)).collect('question'))
    saved = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert saved['status'] == 'FAILED'
    assert saved['error_code'] == 'search_authentication_failed'


def test_sources_api_missing_config(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr('deepdive.providers.search.load_dotenv', lambda *a, **kw: False)
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    with TestClient(app) as client:
        assert client.get('/api/health').json()['search_configured'] is False
        response = client.post('/api/sources', json={'question':'question'})
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'search_not_configured'
        assert client.post('/api/sources', json={'question':'question', 'max_results':11}).status_code == 422


def test_collection_api_returns_fetched_summaries_and_persists_full_text(tmp_path):
    class Provider:
        async def search(self, question, max_results):
            return SearchResults([SearchHit('https://example.com/a', 'A')], 1)
    collector = SourceCollector(Provider(), extractor(lambda request: html_response()), SourceRepository(tmp_path))
    with TestClient(app) as client:
        app.state.source_collector = collector
        response = client.post('/api/sources', json={'question': 'question', 'max_results': 1})
    assert response.status_code == 200
    result = response.json()
    assert result['request_id'] == response.headers['X-Request-ID']
    assert result['valid_sources'] == 1
    assert result['sources'][0]['excerpt']
    assert 'extracted_text' not in result['sources'][0]
    stored = json.loads((tmp_path / (result['id'] + '.json')).read_text())
    assert stored['sources'][0]['extracted_text']


def test_collection_concurrency_and_five_distinct_sources(tmp_path):
    class Provider:
        async def search(self, question, max_results):
            return SearchResults([SearchHit('https://example.com/' + str(index), str(index)) for index in range(10)], 1)
    class Fetcher:
        active = 0
        maximum = 0
        async def fetch(self, url, title):
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0.001)
            self.active -= 1
            source = Source.pending(url, title)
            source.canonical_url = url
            source.extracted_text = 'independent fixture ' + title
            source.content_hash = hashlib.sha256(source.extracted_text.encode()).hexdigest()
            source.fetch_status = 'FETCHED'
            return source
    fetcher = Fetcher()
    result = asyncio.run(SourceCollector(Provider(), fetcher, SourceRepository(tmp_path)).collect('question'))
    assert fetcher.maximum == 5
    assert result['valid_sources'] == 10


def test_deadline_keeps_completed_source_and_marks_cancelled(tmp_path, monkeypatch):
    import deepdive.tools.search.collect as module
    original_timeout = asyncio.timeout
    monkeypatch.setattr(module.asyncio, 'timeout', lambda seconds: original_timeout(0.02 if seconds == 150 else seconds))
    class Provider:
        async def search(self, question, max_results):
            return SearchResults([SearchHit('https://example.com/fast','fast'), SearchHit('https://example.com/slow','slow')], 1)
    class Fetcher:
        async def fetch(self, url, title):
            if title == 'slow':
                await asyncio.sleep(1)
            source = Source.pending(url, title)
            source.canonical_url = url
            source.extracted_text = 'test material'
            source.content_hash = 'test hash'
            source.fetch_status = 'FETCHED'
            return source
    result = asyncio.run(SourceCollector(Provider(), Fetcher(), SourceRepository(tmp_path)).collect('question'))
    assert result['status'] == 'TIMED_OUT'
    assert result['valid_sources'] == 1
    assert [source['fetch_status'] for source in result['sources']] == ['FETCHED', 'CANCELLED']
    stored = json.loads((tmp_path / (result['id'] + '.json')).read_text())
    assert stored == result


def test_failed_search_request_count_is_saved(tmp_path):
    class Provider:
        async def search(self, question, max_results):
            raise ToolFailure('search_timeout', 'safe', 504, requests=2)
    with pytest.raises(ToolFailure):
        asyncio.run(SourceCollector(Provider(), repository=SourceRepository(tmp_path)).collect('question'))
    result = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert result['search_requests'] == 2
