from __future__ import annotations

from lab_report.ingestion.readers import Fragment
from lab_report.models import AgentOutput, Evidence


def evidence_from_fragments(fragments: list[Fragment]) -> list[Evidence]:
    return [
        Evidence(
            id=f"E{i:04}",
            source_file=f.source_file,
            source_sha256=f.source_sha256,
            source_location=f.location,
            quote=f.text,
            method="source_extraction",
        )
        for i, f in enumerate(fragments, 1)
    ]


def validate_output(
    output: AgentOutput, evidence: list[Evidence], fragments: list[Fragment]
) -> AgentOutput:
    valid = {e.id for e in evidence}
    for field in output.fields:
        if field.value is None or not str(field.value).strip():
            field.status = "MISSING"
        elif not field.evidence_ids or any(i not in valid for i in field.evidence_ids):
            field.status = "NEEDS_REVIEW"
        else:
            # ID verification is NOT semantic truth verification. Human review remains required.
            field.status = "NEEDS_REVIEW"
    if output.narrative and (
        not output.narrative_evidence_ids
        or any(i not in valid for i in output.narrative_evidence_ids)
    ):
        output.narrative = None  # refuse to insert unsupported narrative
    return output
