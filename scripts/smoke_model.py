"""One live Agents SDK call. Run with python -m scripts.smoke_model."""
import asyncio
import json
import logging

from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, RunConfig, Runner
from openai import AsyncOpenAI

from deepdive.config import ConfigurationError, ModelConfig


async def probe(config: ModelConfig) -> dict:
    async with AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        max_retries=0,
    ) as client:
        agent = Agent(
            name="DeepDiveConnectivityProbe",
            instructions="This is a connectivity check. Reply with exactly DEEPDIVE_OK.",
            model=OpenAIChatCompletionsModel(model=config.model, openai_client=client),
            model_settings=ModelSettings(
                max_tokens=128,
                extra_body={"thinking": {"type": "disabled"}},
            ),
        )
        result = await asyncio.wait_for(
            Runner.run(
                agent, "Reply with DEEPDIVE_OK.", max_turns=1,
                run_config=RunConfig(tracing_disabled=True),
            ),
            timeout=config.timeout_seconds,
        )
        if str(result.final_output).strip() != "DEEPDIVE_OK":
            raise ValueError("Unexpected probe output")
        usage = result.context_wrapper.usage
        return {
            "status": "ok", "provider": "deepseek", "protocol": "chat_completions",
            "model": config.model, "requests": usage.requests,
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        }


def main() -> int:
    # Suppress third-party request/error logs: upstream errors can contain secrets.
    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        config = ModelConfig.from_env()
        print(json.dumps(asyncio.run(probe(config))))
        return 0
    except ConfigurationError as exc:
        print(json.dumps({"status": "configuration_error", "message": str(exc)}))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "message": "Model probe failed; check credentials, model, network and timeout locally."}))
        return 1

    finally:
        logging.disable(previous_logging_disable)


if __name__ == "__main__":
    raise SystemExit(main())
