from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ResearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depth: Literal['standard','deep'] = 'standard'
    max_budget_usd: float | None = Field(default=None, ge=0.00001, le=10, allow_inf_nan=False)
    max_rounds: int = Field(default=3, ge=1, le=3, strict=True)
    max_search_requests: int = Field(default=30, ge=1, le=30, strict=True)
    max_fetch_requests: int = Field(default=60, ge=1, le=200, strict=True)
    timeout_seconds: int = Field(default=600, ge=1, le=600, strict=True)
    max_sources_per_query: int = Field(default=5, ge=1, le=10, strict=True)
    max_model_calls: int = Field(default=12, ge=1, le=12, strict=True)
    max_total_tokens: int = Field(default=64000, ge=1000, le=200000, strict=True)


class Subquestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=300)
    priority: int = Field(ge=1, le=3)
    evidence_type: str = Field(min_length=1, max_length=100)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subquestions: list[Subquestion] = Field(min_length=1, max_length=3)
    time_sensitive: bool


class Citation(BaseModel):
    excerpt_id: str | None = Field(default=None,max_length=64)
    source_id: str | None = Field(default=None,min_length=1,max_length=64)
    excerpt: str | None = Field(default=None,min_length=20,max_length=600)


class CandidateClaim(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    importance: int = Field(ge=1, le=3)
    citations: list[Citation] = Field(max_length=3)


class Findings(BaseModel):
    claims: list[CandidateClaim] = Field(max_length=8)


class AnalysisPoint(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    text: str = Field(min_length=1,max_length=1400)
    claim_ids: list[str] = Field(min_length=1,max_length=4)


class AnalysisSection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1,max_length=100)
    points: list[AnalysisPoint] = Field(min_length=1,max_length=4)


class Synthesis(BaseModel):
    model_config = ConfigDict(extra='forbid')
    overview: list[AnalysisPoint] = Field(min_length=1,max_length=3)
    sections: list[AnalysisSection] = Field(min_length=1,max_length=6)
    implications: list[AnalysisPoint] = Field(max_length=4)
    open_questions: list[str] = Field(max_length=5)


class AnalysisReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approved_point_ids: list[str] = Field(max_length=31)


class Verdict(BaseModel):
    claim_id: str
    evidence_id: str
    relation: str = Field(pattern="^(supports|contradicts|contextualizes|unverified)$")
    reason: str = Field(max_length=300)


class Verification(BaseModel):
    verdicts: list[Verdict] = Field(max_length=18)
