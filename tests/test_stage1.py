import asyncio
import io
import json
import logging

import httpx2
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from apps.api.main import app, logger
from deepdive.config import ModelConfig
from deepdive.observability.logging import JsonFormatter
from deepdive.providers import llm

SECRET = "private-test-key"
PROMPT = "private-user-question"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ModelConfig, "from_env", classmethod(lambda cls: ModelConfig(api_key=SECRET)))
    with TestClient(app) as test_client:
        yield test_client


def mock_provider(monkeypatch, handler):
    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(llm, "AsyncOpenAI", factory)


def completion(content="answer"):
    return {"id": "offline-test", "object": "chat.completion", "created": 1, "model": "deepseek-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}


def test_agent_success_sdk_usage_and_safe_logs(client, monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    seen = []

    def respond(request):
        seen.append(request)
        assert request.url.path == "/chat/completions"
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 512
        return httpx2.Response(200, json=completion("answer " + SECRET))

    mock_provider(monkeypatch, respond)
    try:
        response = client.post("/api/agent", json={"prompt": PROMPT})
    finally:
        logger.removeHandler(handler)
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "answer [REDACTED]"
    assert data["usage"] == {"requests": 1, "input_tokens": 10, "output_tokens": 3}
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert len(seen) == 1
    logs = stream.getvalue()
    assert SECRET not in logs and PROMPT not in logs and "answer" not in logs
    assert [json.loads(line)["event"] for line in logs.splitlines()] == ["agent.started", "agent.completed"]


@pytest.mark.parametrize("status,expected,code", [(401, 502, "provider_authentication_failed"), (429, 503, "provider_rate_limited"), (500, 502, "provider_error")])
def test_provider_error_is_safe(client, monkeypatch, status, expected, code):
    mock_provider(monkeypatch, lambda request: httpx2.Response(status, json={"error": {"message": SECRET + PROMPT}}))
    response = client.post("/api/agent", json={"prompt": PROMPT})
    assert response.status_code == expected
    assert response.json()["error"]["code"] == code
    assert SECRET not in response.text and PROMPT not in response.text


def test_network_error(client, monkeypatch):
    def fail(request):
        raise httpx2.ConnectError(SECRET, request=request)
    mock_provider(monkeypatch, fail)
    response = client.post("/api/agent", json={"prompt": PROMPT})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unreachable"
    assert SECRET not in response.text


def test_deadline_includes_waiting_for_slot(client):
    service = app.state.model_service
    service.config = ModelConfig(api_key=SECRET, timeout_seconds=0.01)
    service._slot = asyncio.Semaphore(0)
    response = client.post("/api/agent", json={"prompt": PROMPT})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "model_timeout"


@pytest.mark.parametrize("content", ["", " " , "x" * 12001])
def test_invalid_output(client, monkeypatch, content):
    mock_provider(monkeypatch, lambda request: httpx2.Response(200, json=completion(content)))
    response = client.post("/api/agent", json={"prompt": PROMPT})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_model_response"


@pytest.mark.parametrize("payload", [{}, {"prompt": " "}, {"prompt": "x" * 2001}, {"prompt": 123}, {"prompt": "ok", "key": SECRET}])
def test_validation_no_input_echo(client, payload):
    response = client.post("/api/agent", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert SECRET not in response.text


def test_missing_config_is_explicit_and_health_is_liveness(monkeypatch):
    from deepdive.config import ConfigurationError
    def missing(cls):
        raise ConfigurationError("safe message")
    monkeypatch.setattr(ModelConfig, "from_env", classmethod(missing))
    with TestClient(app) as client:
        assert client.get("/api/health").json()["model_configured"] is False
        response = client.post("/api/agent", json={"prompt": "hello"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "model_not_configured"


def test_large_body_rejected_before_json_parse(client):
    response = client.post("/api/agent", content=SECRET + "x" * 32768, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert SECRET not in response.text


def test_root_is_frontend_or_build_instructions(client):
    response=client.get('/')
    assert response.status_code in (200,503)
    assert response.headers['content-type'].startswith('text/html')
    assert response.headers['x-content-type-options']=='nosniff'


def test_research_model_enables_provider_json_mode(monkeypatch):
    import asyncio
    import json
    import httpx2
    from deepdive.providers import llm
    from deepdive.config import ModelConfig
    from openai import AsyncOpenAI
    def handler(request):
        payload=json.loads(request.content)
        assert payload['response_format']=={'type':'json_object'}
        return httpx2.Response(200,json={'id':'test','object':'chat.completion','created':1,'model':'deepseek-flash',
            'choices':[{'index':0,'message':{'role':'assistant','content':'{"ok":true}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
    def client(**kwargs):
        assert kwargs['timeout']==180
        return AsyncOpenAI(**kwargs,http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(llm,'AsyncOpenAI',client)
    result=asyncio.run(llm.ModelService(ModelConfig(api_key='test')).run('Return JSON',instructions='Return JSON only',json_mode=True,timeout_seconds=180))
    assert result['answer']=='{"ok":true}'
