"""Additive SQLite initialization. Never replace or delete an existing database."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from deepdive.config import ROOT
from deepdive.evidence.sources import timestamp
from deepdive.orchestration.models import ResearchSettings
from deepdive.orchestration.state_machine import TERMINAL, validate_transition


def data_directory():
    return Path(os.getenv("DEEPDIVE_DATA_DIR", str(ROOT / "data"))).resolve()


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class ResearchRepository:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else data_directory()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "research.sqlite3"
        for attempt in range(5):
            try:
                with self.connect() as connection:
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                    if version > 1:
                        raise RuntimeError("Unsupported database schema version")
                    connection.executescript((Path(__file__).parent / "migrations/001_initial.sql").read_text())
                break
            except sqlite3.OperationalError as error:
                if 'locked' not in str(error).lower() or attempt == 4:
                    raise
                time.sleep(0.05 * (2 ** attempt))
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, question, settings: ResearchSettings):
        task_id, now = uuid4().hex, timestamp()
        with self.connect() as c:
            c.execute("INSERT INTO research_task VALUES(?,?,?,?,?,?,?,?,?,0)",
                      (task_id,question,"CREATED",now,now,encode(settings.model_dump()),encode(settings.model_dump()),encode({}),None))
            self._event(c,task_id,"task.status",{"status":"CREATED"})
        return self.get(task_id)

    def get(self, task_id):
        with self.connect() as c:
            row=c.execute("SELECT * FROM research_task WHERE id=?",(task_id,)).fetchone()
        if row is None:
            return None
        data=dict(row)
        for name in ("config","budget","usage"):
            data[name]=json.loads(data.pop(name+"_json"))
        data["cancel_requested"]=bool(data["cancel_requested"])
        return data

    def list(self, limit=20, offset=0,statuses=None):
        with self.connect() as c:
            where=' WHERE status IN ('+','.join('?' for _ in statuses)+')' if statuses else ''
            parameters=(*(statuses or []),limit,offset)
            ids=[row[0] for row in c.execute("SELECT id FROM research_task"+where+" ORDER BY created_at DESC LIMIT ? OFFSET ?",parameters)]
        return [self.get(task_id) for task_id in ids]

    def counts(self):
        with self.connect() as c:
            rows=c.execute("SELECT status,COUNT(*) FROM research_task GROUP BY status").fetchall()
        values=dict(rows)
        return {'total':sum(values.values()),'running':sum(count for status,count in values.items() if status not in TERMINAL),
                'completed':values.get('COMPLETED',0),'stopped':sum(count for status,count in values.items() if status in TERMINAL-{'COMPLETED'})}

    def count(self,statuses=None):
        with self.connect() as c:
            where=' WHERE status IN ('+','.join('?' for _ in statuses)+')' if statuses else ''
            return c.execute("SELECT COUNT(*) FROM research_task"+where,statuses or []).fetchone()[0]

    def _event(self,c,task_id,event,data):
        c.execute("INSERT INTO task_event(task_id,type,created_at,data_json) VALUES(?,?,?,?)",(task_id,event,timestamp(),encode(data)))

    def event(self,task_id,event,data):
        with self.connect() as c:
            self._event(c,task_id,event,data)

    def events(self,task_id):
        with self.connect() as c:
            rows=c.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id",(task_id,)).fetchall()
        return [{**dict(row),"data":json.loads(row["data_json"])} for row in rows]

    def events_after(self,task_id,cursor=0,limit=100):
        with self.connect() as c:
            rows=c.execute("SELECT id,type,created_at,data_json FROM task_event WHERE task_id=? AND id>? ORDER BY id LIMIT ?",(task_id,cursor,limit)).fetchall()
        return [{'id':row['id'],'type':row['type'],'created_at':row['created_at'],'data':json.loads(row['data_json'])} for row in rows]

    def transition(self,task_id,new,error=None):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT status FROM research_task WHERE id=?",(task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            validate_transition(row[0],new)
            c.execute("UPDATE research_task SET status=?,updated_at=?,error_message=? WHERE id=?",(new,timestamp(),error,task_id))
            self._event(c,task_id,"task.status",{"status":new,"error_code":error})

    def next_created(self):
        with self.connect() as c:
            row=c.execute("SELECT id FROM research_task WHERE status='CREATED' ORDER BY created_at LIMIT 1").fetchone()
        return row[0] if row else None

    def recover(self):
        with self.connect() as c:
            rows=c.execute("SELECT id,status FROM research_task").fetchall()
        for row in rows:
            if row["status"] not in TERMINAL | {"CREATED"}:
                self.transition(row["id"],"FAILED","worker_restarted")

    def cancel(self,task_id):
        task=self.get(task_id)
        if task is None:
            return None
        with self.connect() as c:
            c.execute("UPDATE research_task SET cancel_requested=1,updated_at=? WHERE id=? AND cancel_requested=0 AND status NOT IN ('COMPLETED','FAILED','CANCELLED','BUDGET_EXCEEDED','TIMED_OUT')",(timestamp(),task_id))
            if c.total_changes:
                self._event(c,task_id,'task.cancel_requested',{})
        return self.get(task_id)

    def usage(self,task_id,usage):
        with self.connect() as c:
            c.execute("UPDATE research_task SET usage_json=?,updated_at=? WHERE id=?",(encode(usage),timestamp(),task_id))

    def add_subtasks(self,task_id,plan):
        with self.connect() as c:
            for item in plan.subquestions:
                c.execute("INSERT INTO research_subtask VALUES(?,?,?,?,?,?,?)",(uuid4().hex,task_id,item.question,item.objective,item.priority,"CREATED",item.evidence_type))

    def subtask_status(self,task_id,question,status):
        with self.connect() as c:
            c.execute("UPDATE research_subtask SET status=? WHERE task_id=? AND question=?",(status,task_id,question))

    def add_sources(self,task_id,sources):
        with self.connect() as c:
            for source in sources:
                duplicate=c.execute("SELECT id FROM source WHERE task_id=? AND (canonical_url=? OR content_hash=?) AND content_hash IS NOT NULL",(task_id,source["canonical_url"],source["content_hash"])).fetchone()
                if duplicate and source["fetch_status"]=="FETCHED":
                    continue
                c.execute("INSERT OR IGNORE INTO source VALUES(?,?,?,?,?,?)",(source["id"],task_id,source["url"],source["canonical_url"],source["content_hash"],encode(source)))

    def sources(self,task_id):
        with self.connect() as c:
            return [json.loads(row[0]) for row in c.execute("SELECT data_json FROM source WHERE task_id=?",(task_id,))]

    def add_claim(self,task_id,text,importance):
        claim_id=uuid4().hex
        with self.connect() as c:
            c.execute("INSERT INTO claim VALUES(?,?,?,?,?,?,?)",(claim_id,task_id,text,importance,"UNVERIFIED","unknown","尚未完成证据核验。"))
        return claim_id

    def add_evidence(self,task_id,claim_id,source_id,excerpt,location):
        evidence_id=uuid4().hex
        with self.connect() as c:
            source=c.execute("SELECT data_json FROM source WHERE id=? AND task_id=?",(source_id,task_id)).fetchone()
            claim=c.execute("SELECT id FROM claim WHERE id=? AND task_id=?",(claim_id,task_id)).fetchone()
            body=json.loads(source[0]) if source else None
            if not body or not claim or body['fetch_status']!='FETCHED' or excerpt not in body['extracted_text']:
                raise ValueError("Evidence must link same-task claim and a literal fetched source excerpt")
            c.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?)",(evidence_id,task_id,source_id,excerpt,location,"与候选主张关联，待核验。","UNVERIFIED"))
            c.execute("INSERT INTO claim_evidence VALUES(?,?,?)",(claim_id,evidence_id,"contextualizes"))
        return evidence_id

    def materials(self,task_id):
        with self.connect() as c:
            claims=[dict(row) for row in c.execute("SELECT * FROM claim WHERE task_id=?",(task_id,))]
            evidence=[dict(row) for row in c.execute("SELECT e.*,ce.claim_id,ce.relation FROM evidence e JOIN claim_evidence ce ON ce.evidence_id=e.id WHERE e.task_id=?",(task_id,))]
            subtasks=[dict(row) for row in c.execute("SELECT * FROM research_subtask WHERE task_id=? ORDER BY priority",(task_id,))]
        return {"claims":claims,"evidence":evidence,"sources":self.sources(task_id),"subtasks":subtasks}

    def verdict(self,claim_id,evidence_id,relation,status,reason):
        with self.connect() as c:
            c.execute("UPDATE claim_evidence SET relation=? WHERE claim_id=? AND evidence_id=?",(relation,claim_id,evidence_id))
            c.execute("UPDATE evidence SET verification_status=?,relevance_note=? WHERE id=?",(status,reason,evidence_id))

    def claim_status(self,claim_id,status,note):
        with self.connect() as c:
            c.execute("UPDATE claim SET verification_status=?,confidence_label=?,limitation_note=? WHERE id=?",(status,"evidence_linked" if status=="SUPPORTED" else "limited",note,claim_id))

    def save_report(self,task_id,markdown):
        with self.connect() as c:
            version=c.execute("SELECT COALESCE(MAX(version),0)+1 FROM report WHERE task_id=?",(task_id,)).fetchone()[0]
            c.execute("INSERT INTO report VALUES(?,?,?,?,?)",(uuid4().hex,task_id,markdown,timestamp(),version))
        reports=self.directory/"reports"
        reports.mkdir(exist_ok=True,mode=0o700)
        # Immutable version paths preserve previous reports on retry or recovery.
        path=reports/(task_id+"-v"+str(version)+".md")
        with path.open("x",encoding="utf-8") as f:
            f.write(markdown)
        path.chmod(0o600)

    def report(self,task_id):
        with self.connect() as c:
            row=c.execute("SELECT markdown_content FROM report WHERE task_id=? ORDER BY version DESC LIMIT 1",(task_id,)).fetchone()
        return row[0] if row else None
