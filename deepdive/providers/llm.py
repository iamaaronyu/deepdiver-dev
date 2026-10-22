"""Bounded single-turn DeepSeek adapter using the installed Agents SDK."""
import asyncio
from dataclasses import dataclass
from time import monotonic

from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, RunConfig, Runner
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from deepdive.config import ModelConfig


@dataclass
class ModelFailure(Exception):
    code: str
    message: str
    http_status: int


class ModelService:
    def __init__(self, config: ModelConfig):
        self.config = config
        self._slot = asyncio.Semaphore(1)

    async def run(self, prompt: str, *, instructions=None, max_tokens=512, json_mode=False, timeout_seconds=None) -> dict:
        started = monotonic()
        timeout_seconds=timeout_seconds or self.config.timeout_seconds
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self._slot:
                    async with AsyncOpenAI(
                        api_key=self.config.api_key, base_url=self.config.base_url,
                        timeout=timeout_seconds, max_retries=0,
                    ) as client:
                        agent = Agent(
                            name="DeepDiveMinimalAgent",
                            instructions=instructions or "Answer the user's question concisely. You have no search tools. Do not claim to have searched or verified external sources.",
                            model=OpenAIChatCompletionsModel(model=self.config.model, openai_client=client),
                            model_settings=ModelSettings(max_tokens=max_tokens, extra_body={"thinking": {"type": "disabled"}, **({"response_format": {"type": "json_object"}} if json_mode else {})}),
                        )
                        result = await Runner.run(agent, prompt, max_turns=1, run_config=RunConfig(tracing_disabled=True))
            text = result.final_output
            if not isinstance(text, str) or not text.strip():
                raise ModelFailure("invalid_model_response", "模型未返回有效文本。", 502)
            if len(text) > 12000:
                raise ModelFailure("invalid_model_response", "模型输出超出长度限制。", 502)
            usage = result.context_wrapper.usage
            return {"answer": text.replace(self.config.api_key, "[REDACTED]"), "model": self.config.model,
                    "usage": {"requests": usage.requests, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
                    "duration_ms": round((monotonic() - started) * 1000)}
        except ModelFailure:
            raise
        except (TimeoutError, APITimeoutError):
            raise ModelFailure("model_timeout", "模型调用超时，请稍后重试。", 504) from None
        except AuthenticationError:
            raise ModelFailure("provider_authentication_failed", "模型服务认证失败，请在本地检查密钥。", 502) from None
        except RateLimitError:
            raise ModelFailure("provider_rate_limited", "模型服务限流或额度不足，请稍后重试。", 503) from None
        except APIConnectionError:
            raise ModelFailure("provider_unreachable", "无法连接模型服务，请检查网络。", 502) from None
        except APIStatusError:
            raise ModelFailure("provider_error", "模型服务返回错误，请检查模型配置或稍后重试。", 502) from None
        except Exception:
            raise ModelFailure("model_execution_failed", "模型执行失败。", 502) from None
