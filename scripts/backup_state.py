"""Consistent SQLite backup including tasks, complete sources, evidence and reports."""
import os
import sqlite3
from datetime import datetime,timezone
from uuid import uuid4

from deepdive.storage.database import ResearchRepository


def main():
    repository=ResearchRepository()
    folder=repository.directory/'backups'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]+'.sqlite3')
    os.close(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600))
    with repository.connect() as source,sqlite3.connect(path) as destination:
        source.backup(destination)
    print(str(path))


if __name__=='__main__':
    main()
