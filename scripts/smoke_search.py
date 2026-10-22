"""Real stage 2 search/extraction probe, saving fetched text only in ignored data/."""
import argparse
import asyncio
import json

from deepdive.config import ConfigurationError
from deepdive.observability.logging import configure_logging
from deepdive.providers.registry import create_source_collector
from deepdive.tools.search.models import ToolFailure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default="site:docs.python.org asyncio tasks queues streams subprocess synchronization")
    args = parser.parse_args()
    configure_logging()
    try:
        collection = asyncio.run(create_source_collector().collect(args.question))
        print(json.dumps({key: collection[key] for key in ("id", "status", "valid_sources", "search_requests", "provider_usage")}))
        print("Source records: data/sources/" + collection["id"] + ".json")
        return 0 if collection["valid_sources"] >= 5 else 1
    except ConfigurationError:
        print(json.dumps({"status": "configuration_error", "code": "search_not_configured", "message": "Check SEARCH_PROVIDER and its API key in local .env."}))
        return 2
    except ToolFailure as exc:
        print(json.dumps({"status": "failed", "code": exc.code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
