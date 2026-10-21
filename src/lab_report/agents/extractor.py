from __future__ import annotations

from lab_report.ingestion.readers import Fragment
from lab_report.models import AgentOutput, ExtractedField, LLMResponse
from lab_report.validation.evidence import evidence_from_fragments, validate_output


def extract_section(
    section_id: str,
    required_fields: list[str],
    fragments: list[Fragment],
    *,
    model: str = "gemma4:26b",
    host: str = "http://localhost:11434",
    max_fragments: int = 30,
) -> tuple[AgentOutput, list]:
    # MVP uses keyword-ranked retrieval instead of vector RAG: deterministic and auditable.
    terms = set(" ".join(required_fields).lower().replace("_", " ").split())
    ranked = sorted(fragments, key=lambda f: sum(t in f.text.lower() for t in terms), reverse=True)
    selected = ranked[:max_fragments]
    evidence = evidence_from_fragments(selected)
    passages = "\n".join(
        f"[{e.id}] {e.source_file} {e.source_location}: {f.text[:1500]}"
        for e, f in zip(evidence, selected, strict=True)
    )
    prompt = (
        f"Section: {section_id}\nRequired fields: {required_fields}\n"
        "Return fields ONLY if directly supported by snippets. Attach evidence IDs "
        "from the bracketed IDs. Missing values must be null with empty evidence IDs. "
        "Do not infer standards, instrument calibration or sample numbers. "
        "Optional narrative must also list all supporting IDs.\n\n" + passages
    )
    from ollama import Client

    response = Client(host=host).chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a careful laboratory data extraction agent. No invented data.",
            },
            {"role": "user", "content": prompt},
        ],
        format=LLMResponse.model_json_schema(),
        options={"temperature": 0, "num_ctx": 8192, "num_predict": 2048},
    )
    if not response.message.content:
        raise RuntimeError(f"Model {model} returned an empty response for section {section_id}")
    parsed = LLMResponse.model_validate_json(response.message.content)
    by_name = {f.name: f for f in parsed.fields}
    output = AgentOutput(
        section_id=section_id,
        fields=[
            ExtractedField(
                field_name=name,
                value=by_name[name].value if name in by_name else None,
                evidence_ids=by_name[name].evidence_ids if name in by_name else [],
            )
            for name in required_fields
        ],
        narrative=parsed.narrative,
        narrative_evidence_ids=parsed.narrative_evidence_ids,
    )
    return validate_output(output, evidence, selected), evidence
