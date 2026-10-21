"""Provenance data model: every value placed in the report is a SlotResult."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal[
    "VERIFIED",  # deterministic extraction, value found literally in the cited source block
    "COMPUTED",  # derived deterministically from cited inputs
    "NEEDS_REVIEW",  # LLM output; citations valid but meaning must be checked by a person
    "CONFLICT",  # two sources disagree
    "MISSING",  # no source found
    "NOT_IMPLEMENTED",  # slot exists in the template but no extractor/calculation yet
]


class Block(BaseModel):
    """One addressable piece of a source document: a text line or a table cell."""

    id: str  # "<sha8>:p<page>:l<n>" or "<sha8>:p<page>:t<t>r<r>c<c>"
    doc_sha256: str
    file: str
    doc_type: str
    page: int
    kind: Literal["line", "cell"]
    bbox: tuple[float, float, float, float]
    text: str
    table: int | None = None
    row: int | None = None
    col: int | None = None


class SlotResult(BaseModel):
    slot: str
    value: str | None
    status: Status
    method: str  # kv | table | llm | compute | format | none
    evidence_ids: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)  # slots a computed value depends on
    reason: str | None = None
    model: str | None = None


class RowGroup(BaseModel):
    """Repeated table rows (e.g. one per specimen); each cell is a SlotResult."""

    name: str
    rows: list[dict[str, SlotResult]] = Field(default_factory=list)
    status: Status = "VERIFIED"
    reason: str | None = None
