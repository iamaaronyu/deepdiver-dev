"""Dated conservative price snapshot; estimates never represent an account invoice."""
from urllib.parse import urlsplit
from deepdive.providers.deepseek_tools import DeepSeekSearch


def price_profile(model,collector):
    config=getattr(model,'config',None)
    if config and config.model=='deepseek-flash' and urlsplit(config.base_url).hostname=='api.deepseek.com' and isinstance(getattr(collector,'provider',None),DeepSeekSearch):
        return {'model_input_per_million':0.3,'model_output_per_million':1.2,
                'search_per_request':0.00075,'fetch_per_request':0.00075,
                'as_of':'2026-10-22','source':'https://api-docs.deepseek.com/quick_start/pricing/',
                'method':'peak cache-miss model rates; all tool attempts priced as successful, ignoring promotions'}
    return None
