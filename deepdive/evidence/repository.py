"""Stage 2 source collections as atomic JSON files; stage 3 introduces relational evidence."""
import json
import os
import tempfile
from pathlib import Path

from deepdive.config import ROOT


class SourceRepository:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path(os.getenv("DEEPDIVE_DATA_DIR", str(ROOT / "data"))) / "sources"

    def save(self, collection: dict):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".collection-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(collection, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.directory / (collection["id"] + ".json"))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
