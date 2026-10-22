from pydantic import BaseModel,ConfigDict,Field
from deepdive.orchestration.models import ResearchSettings


class ResearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    question: str=Field(min_length=1,max_length=2000)
    settings: ResearchSettings=Field(default_factory=ResearchSettings)


class TaskResponse(BaseModel):
    id: str
    question: str
    status: str
    created_at: str
    updated_at: str
    config: ResearchSettings
    budget: dict
    usage: dict
    error_message: str | None
    cancel_requested: bool


class ClaimSummary(BaseModel):
    id: str
    task_id: str
    claim_text: str
    importance: int
    verification_status: str
    confidence_label: str
    limitation_note: str


class EvidenceSummary(BaseModel):
    id: str
    task_id: str
    source_id: str
    quote_or_excerpt: str
    location_hint: str | None
    relevance_note: str
    verification_status: str
    claim_id: str
    relation: str


class SubtaskSummary(BaseModel):
    id: str
    task_id: str
    question: str
    objective: str
    priority: int
    status: str
    result_summary: str


from apps.api.schemas.sources import SourceSummary


class MaterialResponse(BaseModel):
    claims: list[ClaimSummary]
    evidence: list[EvidenceSummary]
    sources: list[SourceSummary]
    subtasks: list[SubtaskSummary]
