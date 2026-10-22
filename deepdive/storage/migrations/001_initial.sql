CREATE TABLE IF NOT EXISTS research_task (
 id TEXT PRIMARY KEY, question TEXT NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 config_json TEXT NOT NULL, budget_json TEXT NOT NULL, usage_json TEXT NOT NULL,
 error_message TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS research_subtask (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES research_task(id),
 question TEXT NOT NULL, objective TEXT NOT NULL, priority INTEGER NOT NULL,
 status TEXT NOT NULL, result_summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS source (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES research_task(id),
 url TEXT NOT NULL, canonical_url TEXT NOT NULL, content_hash TEXT, data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS source_task ON source(task_id);
CREATE TABLE IF NOT EXISTS claim (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES research_task(id),
 claim_text TEXT NOT NULL, importance INTEGER NOT NULL,
 verification_status TEXT NOT NULL, confidence_label TEXT NOT NULL,
 limitation_note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES research_task(id),
 source_id TEXT NOT NULL REFERENCES source(id), quote_or_excerpt TEXT NOT NULL,
 location_hint TEXT, relevance_note TEXT NOT NULL, verification_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim_evidence (
 claim_id TEXT NOT NULL REFERENCES claim(id), evidence_id TEXT NOT NULL REFERENCES evidence(id),
 relation TEXT NOT NULL CHECK(relation IN ('supports','contradicts','contextualizes')),
 PRIMARY KEY(claim_id,evidence_id)
);
CREATE TABLE IF NOT EXISTS report (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES research_task(id),
 markdown_content TEXT NOT NULL, created_at TEXT NOT NULL, version INTEGER NOT NULL,
 UNIQUE(task_id,version)
);
CREATE TABLE IF NOT EXISTS task_event (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES research_task(id),
 type TEXT NOT NULL, created_at TEXT NOT NULL, data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS task_event_task ON task_event(task_id,id);
PRAGMA user_version=1;
