"""Run API and independent worker together; stop both with Ctrl-C."""
import signal
import subprocess
import sys
import time
from deepdive.config import ROOT
from deepdive.storage.database import ResearchRepository


def main():
    children=[]
    stopping=False
    def stop(*args):
        nonlocal stopping
        stopping=True
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,stop)
    try:
        ResearchRepository()
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port','8000','--no-access-log'],cwd=ROOT))
        children.append(subprocess.Popen([sys.executable,'-m','deepdive.worker'],cwd=ROOT))
        while not stopping:
            for child in children:
                if child.poll() is not None:
                    return child.returncode or 1
            time.sleep(0.2)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__=='__main__':
    raise SystemExit(main())
