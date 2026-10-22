import hashlib
import json
from pathlib import Path

from deepdive.config import ROOT
from deepdive.orchestration.models import ResearchSettings

SUITE=ROOT/'evals/research-v1.json'
PROFILES={
    'standard':ResearchSettings(depth='standard',max_rounds=1,max_search_requests=6,max_fetch_requests=24,max_sources_per_query=3,max_model_calls=8,timeout_seconds=240,max_budget_usd=.10),
    'deep':ResearchSettings(depth='deep',max_rounds=2,max_search_requests=12,max_fetch_requests=36,max_sources_per_query=3,max_model_calls=12,timeout_seconds=360,max_budget_usd=.10),
}


def load_suite(path=SUITE):
    raw=Path(path).read_bytes()
    suite=json.loads(raw)
    cases=suite['cases']
    if len(cases)<10 or len({c['id'] for c in cases})!=len(cases):
        raise ValueError('At least ten uniquely identified cases are required')
    required={'fact','comparison','current','conflict','insufficient'}
    if not required<={c['category'] for c in cases}:
        raise ValueError('Missing required evaluation category')
    for case in cases:
        if not case['question'] or not case['aspects'] or not case['reference_rubric']:
            raise ValueError('Cases require a question, coverage aspects and a reference rubric')
    return suite,hashlib.sha256(raw).hexdigest()
