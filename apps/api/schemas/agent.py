from pydantic import BaseModel, ConfigDict, Field


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=2000)


class Usage(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int


class AgentResponse(BaseModel):
    request_id: str
    answer: str
    model: str
    usage: Usage
    duration_ms: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorDetail
