"""DeepSeek settings; never print secret values."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 60

    @classmethod
    def from_env(cls) -> "ModelConfig":
        load_dotenv(ROOT / ".env", override=False)
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not key or key in {"your-api-key", "replace-me"}:
            raise ConfigurationError("DEEPSEEK_API_KEY is not configured; set it in local .env.")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
        try:
            parsed = urlsplit(base_url)
        except ValueError:
            raise ConfigurationError("DEEPSEEK_BASE_URL is invalid.") from None
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ConfigurationError("DEEPSEEK_BASE_URL must be an HTTPS URL without credentials, query or fragment.")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
        if not model:
            raise ConfigurationError("DEEPSEEK_MODEL must not be empty.")
        try:
            timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
        except ValueError:
            raise ConfigurationError("MODEL_TIMEOUT_SECONDS must be a number from 1 to 120.") from None
        if not 1 <= timeout <= 120:
            raise ConfigurationError("MODEL_TIMEOUT_SECONDS must be a number from 1 to 120.")
        return cls(key, base_url, model, timeout)
