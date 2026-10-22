import os
from dotenv import load_dotenv

from deepdive.config import ConfigurationError, ROOT
from deepdive.providers.deepseek_tools import DeepSeekToolsConfig, DeepSeekSearch, DeepSeekFetch
from deepdive.providers.search import SearchConfig, TavilySearch
from deepdive.tools.search.collect import SourceCollector


def create_source_collector():
    load_dotenv(ROOT / ".env", override=False)
    provider = os.getenv("SEARCH_PROVIDER", "deepseek").strip().lower()
    if provider == "deepseek":
        config = DeepSeekToolsConfig.from_env()
        return SourceCollector(DeepSeekSearch(config), DeepSeekFetch(config))
    if provider == "tavily":
        return SourceCollector(TavilySearch(SearchConfig.from_env()))
    raise ConfigurationError("SEARCH_PROVIDER must be deepseek or tavily.")
