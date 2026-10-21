from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    id: str
    source_file: str
    source_sha256: str
    source_location: str
    quote: str | None = None
    method: str


class ExtractedField(BaseModel):
    field_name: str
    value: str | None
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["VERIFIED", "NEEDS_REVIEW", "MISSING", "CONFLICT"] = "NEEDS_REVIEW"


class AgentOutput(BaseModel):
    section_id: str
    fields: list[ExtractedField] = Field(default_factory=list)
    narrative: str | None = None
    narrative_evidence_ids: list[str] = Field(default_factory=list)


class LLMField(BaseModel):
    name: str
    value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class LLMResponse(BaseModel):
    fields: list[LLMField] = Field(default_factory=list)
    narrative: str | None = None
    narrative_evidence_ids: list[str] = Field(default_factory=list)
