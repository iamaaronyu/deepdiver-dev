import asyncio
import json

import httpx
import pytest

from deepdive.providers.deepseek_tools import DeepSeekToolsConfig, DeepSeekSearch, DeepSeekFetch
from deepdive.providers.registry import create_source_collector
from deepdive.tools.search.models import ToolFailure


async def public_dns(host, port):
    return '93.184.216.34'


def test_default_registry_reuses_deepseek_key(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-secret')
    collector = create_source_collector()
    assert isinstance(collector.provider, DeepSeekSearch)
    assert isinstance(collector.extractor, DeepSeekFetch)
    assert 'test-secret' not in repr(DeepSeekToolsConfig.from_env())


def test_search_official_schema():
    def respond(request):
        assert request.url == 'https://api.deepseek.com/v1/tools/search'
        assert request.headers['authorization'] == 'Bearer test-secret'
        assert json.loads(request.content) == {'query':'question','count':5,'need_content':False}
        return httpx.Response(200, json={'results':[{'url':'https://example.com/','title':'Title','snippet':'Snippet','site_name':'Publisher','date':'2026-10-01T00:00:00Z'}]})
    result = asyncio.run(DeepSeekSearch(DeepSeekToolsConfig('test-secret'), transport=httpx.MockTransport(respond)).search('question',5))
    assert result.requests == 1
    assert result.provider_usage == {'provider':'deepseek','search_successes':1}
    assert result.hits[0].publisher == 'Publisher'
    assert result.hits[0].published_at == '2026-10-01T00:00:00Z'


def test_long_query_rejected_without_request():
    with pytest.raises(ToolFailure) as failure:
        asyncio.run(DeepSeekSearch(DeepSeekToolsConfig('test-secret')).search('x'*129))
    assert failure.value.http_status == 422
    assert failure.value.requests == 0


@pytest.mark.parametrize('status,code,requests', [(401,'tools_authentication_failed',1), (402,'tools_insufficient_balance',1), (403,'tools_security_rejected',1), (429,'tools_rate_limited',2), (504,'tools_timeout',2)])
def test_tools_errors_safe_and_retry_bounded(status,code,requests):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={'error':{'message':'test-secret'}})
    with pytest.raises(ToolFailure) as failure:
        asyncio.run(DeepSeekSearch(DeepSeekToolsConfig('test-secret'), transport=httpx.MockTransport(respond)).search('question'))
    assert failure.value.code == code
    assert failure.value.requests == len(calls) == requests
    assert 'test-secret' not in str(failure.value)


def test_fetch_markdown_and_redirect_boundary():
    def respond(request):
        assert request.url == 'https://api.deepseek.com/v1/tools/fetch'
        assert json.loads(request.content) == {'url':'https://example.com/article'}
        return httpx.Response(200,json={'title':'Actual title','content':'# Actual page\n'+('source body '*20)})
    source = asyncio.run(DeepSeekFetch(DeepSeekToolsConfig('test-secret'), transport=httpx.MockTransport(respond),resolver=public_dns).fetch('https://example.com/article'))
    assert source.fetch_status == 'FETCHED'
    assert source.fetch_provider == 'deepseek_fetch'
    assert source.redirect_chain_verified is False
    assert source.fetch_requests == source.fetch_successes == 1
    assert source.extracted_text.startswith('# Actual page')
    assert source.published_at is None
    assert source.content_hash


def test_fetch_initial_private_target_rejected_without_provider_call():
    from deepdive.tools.web_extract.security import resolve_public
    def unexpected(request):
        pytest.fail('Provider must not be called for a private target')
    source=asyncio.run(DeepSeekFetch(DeepSeekToolsConfig('test-secret'),transport=httpx.MockTransport(unexpected),resolver=resolve_public).fetch('http://127.0.0.1/'))
    assert source.error_code == 'unsafe_address'
    assert source.fetch_requests == 0


def test_fetch_unavailable_content_not_substituted_with_summary():
    source=asyncio.run(DeepSeekFetch(DeepSeekToolsConfig('test-secret'),transport=httpx.MockTransport(lambda request:httpx.Response(404,json={'error':{'message':'test-secret'}})),resolver=public_dns).fetch('https://example.com/'))
    assert source.fetch_status == 'FAILED'
    assert source.error_code == 'tools_content_unavailable'
    assert source.extracted_text == ''
    assert source.fetch_requests == 1


def test_fetch_deadline_preserves_attempt_count():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200,json={'title':'Title','content':'body '*100})
    source=asyncio.run(DeepSeekFetch(DeepSeekToolsConfig('test-secret'),transport=httpx.MockTransport(slow),resolver=public_dns,timeout=0.01).fetch('https://example.com/'))
    assert source.error_code == 'tools_timeout'
    assert source.fetch_requests == 1
    assert source.fetch_successes == 0
