"""Single-owner local worker. Separate process from FastAPI; SQLite is the queue."""
import asyncio
import fcntl
import logging
import signal

from deepdive.config import ModelConfig
from deepdive.observability.logging import configure_logging
from deepdive.orchestration.controller import ResearchController
from deepdive.providers.llm import ModelService
from deepdive.providers.registry import create_source_collector
from deepdive.storage.database import ResearchRepository


async def serve(repository):
    controller=ResearchController(repository,ModelService(ModelConfig.from_env()),create_source_collector())
    stopping=asyncio.Event()
    active=None
    def stop():
        stopping.set()
        if active and not active.done():
            active.cancel()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(sig,stop)
    repository.recover()
    while not stopping.is_set():
        task_id=repository.next_created()
        if task_id:
            active=asyncio.create_task(controller.run(task_id))
            await active
            active=None
        else:
            try:
                await asyncio.wait_for(stopping.wait(),timeout=0.5)
            except TimeoutError:
                pass


def main():
    logger=configure_logging()
    try:
        repository=ResearchRepository()
        # OS releases the advisory lock on crash. Only its holder may recover stale tasks.
        with (repository.directory/'worker.lock').open('a') as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                logger.error('',extra={'event':'worker.startup','error_code':'worker_already_running'})
                return 1
            logger.info('',extra={'event':'worker.startup','status':'ready'})
            asyncio.run(serve(repository))
        return 0
    except Exception:
        logger.error('',extra={'event':'worker.failed','error_code':'worker_startup_or_storage_failed'})
        return 1


if __name__=='__main__':
    raise SystemExit(main())
