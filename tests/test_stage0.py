import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from deepdive.config import ConfigurationError, ModelConfig
from scripts import smoke_model


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    monkeypatch.setattr("deepdive.config.load_dotenv", lambda *a, **kw: False)
    monkeypatch.setattr("deepdive.providers.search.load_dotenv", lambda *a, **kw: False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "MODEL_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def test_health_is_liveness_only():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "stage": "4", "scope": "process", "model_configured": False, "search_configured": False, "worker_running": False}


def test_missing_key():
    with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
        ModelConfig.from_env()


def test_secret_not_in_repr(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-value")
    config = ModelConfig.from_env()
    assert "secret-test-value" not in repr(config)
    assert config.base_url == "https://api.deepseek.com"


@pytest.mark.parametrize("timeout", ["bad", "nan", "inf", "0", "121"])
def test_bad_timeout(monkeypatch, timeout):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-value")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", timeout)
    with pytest.raises(ConfigurationError, match="MODEL_TIMEOUT_SECONDS"):
        ModelConfig.from_env()


@pytest.mark.parametrize("url", ["http://api.deepseek.com", "https://user:secret@example.com", "https://example.com?key=secret"])
def test_unsafe_provider_url(monkeypatch, url):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-value")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", url)
    with pytest.raises(ConfigurationError):
        ModelConfig.from_env()


def test_probe_configuration_error_exit(capsys):
    assert smoke_model.main() == 2
    assert "configuration_error" in capsys.readouterr().out


def test_upstream_error_is_sanitized(monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-value")

    async def failed_probe(config):
        raise RuntimeError("upstream leaked secret-test-value")

    monkeypatch.setattr(smoke_model, "probe", failed_probe)
    assert smoke_model.main() == 1
    output = capsys.readouterr().out
    assert "secret-test-value" not in output
    assert "RuntimeError" in output


def test_actual_sdk_uses_chat_completions_and_reads_usage(monkeypatch):
    """Exercise installed Agent/Runner against a local mock, not a live provider."""
    import asyncio
    import json

    import httpx2
    from openai import AsyncOpenAI

    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash"
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["max_tokens"] == 128
        return httpx2.Response(200, json={
            "id": "offline-test", "object": "chat.completion", "created": 1,
            "model": "deepseek-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "DEEPDIVE_OK"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        })

    def client_factory(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(smoke_model, "AsyncOpenAI", client_factory)
    result = asyncio.run(smoke_model.probe(ModelConfig(api_key="offline-test-key")))
    assert len(requests) == 1
    assert result["status"] == "ok"
    assert result["requests"] == 1
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 4
