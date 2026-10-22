"""Offline tests must never load a user's real credentials or call paid providers."""
import pytest


@pytest.fixture(autouse=True)
def isolate_credentials(monkeypatch,tmp_path):
    monkeypatch.setenv("DEEPDIVE_DATA_DIR",str(tmp_path))
    for module in ('deepdive.config', 'deepdive.providers.search', 'deepdive.providers.deepseek_tools', 'deepdive.providers.registry'):
        monkeypatch.setattr(module + '.load_dotenv', lambda *args, **kwargs: False)
    for name in ('DEEPSEEK_API_KEY', 'TAVILY_API_KEY', 'SEARCH_PROVIDER'):
        monkeypatch.delenv(name, raising=False)
