"""LLM extraction (Gemma via Ollama). The model only sees blocks of the slot's source document
type and must cite their ids; output is never better than NEEDS_REVIEW."""

from __future__ import annotations

import hashlib
from typing import Protocol

from pydantic import BaseModel, Field

from lab_report.pipeline.extract import norm
from lab_report.pipeline.index import Index
from lab_report.pipeline.models import SlotResult

MAX_PROMPT_CHARS = 24_000  # ~6k tokens; keeps prompt + answer inside num_ctx below

SYSTEM = (
    "You are a careful laboratory report assistant. Use only the numbered source snippets. "
    "Never invent values, standards, batch numbers or results. If the snippets do not "
    "support an answer, return value null and no evidence ids."
)


class LLMAnswer(BaseModel):
    value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class LLMClient(Protocol):
    name: str

    def answer(self, system: str, prompt: str) -> str:
        """Return JSON matching LLMAnswer."""
        ...


class OllamaClient:
    def __init__(self, model: str, host: str):
        from ollama import Client

        self._client = Client(host=host)
        self._model = model
        try:
            listed = {m.model: m.digest for m in self._client.list().models}
            digest = listed.get(model) or listed.get(f"{model}:latest")
        except Exception:  # noqa: BLE001 - digest is informational only
            digest = None
        self.name = f"ollama:{model}@{(digest or 'unknown')[:12]}"

    def answer(self, system: str, prompt: str) -> str:
        num_ctx = min(32_768, max(4096, (len(system) + len(prompt)) // 3 + 1024))
        response = self._client.chat(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            format=LLMAnswer.model_json_schema(),
            options={"temperature": 0, "num_ctx": num_ctx, "num_predict": 512},
        )
        if not response.message.content:
            raise RuntimeError(f"{self.name} returned an empty response")
        return response.message.content


def extract_llm(slot: str, spec: dict, index: Index, client: LLMClient | None) -> SlotResult:
    if client is None:
        return SlotResult(
            slot=slot,
            value=None,
            status="MISSING",
            method="llm",
            reason="LLM disabled for this run",
        )
    blocks = index.lines(spec["source"])
    if not blocks:
        return SlotResult(
            slot=slot,
            value=None,
            status="MISSING",
            method="llm",
            reason=f"no {spec['source']} document indexed",
        )
    snippets, used = [], 0
    for b in blocks:
        line = f"[{b.id}] {b.text}"
        if used + len(line) > MAX_PROMPT_CHARS:
            break
        snippets.append(line)
        used += len(line) + 1
    truncated = len(snippets) < len(blocks)
    prompt = (
        f"Task for report field '{slot}': {spec['instruction']}\n"
        "Return JSON {value, evidence_ids}; evidence_ids are the bracketed ids of every "
        "snippet you used.\n\nSnippets:\n" + "\n".join(snippets)
    )
    raw = client.answer(SYSTEM, prompt)
    answer = LLMAnswer.model_validate_json(raw)
    prompt_hash = hashlib.sha256((SYSTEM + prompt).encode()).hexdigest()[:12]
    allowed = {b.id for b in blocks}
    bad = [e for e in answer.evidence_ids if e not in allowed]
    notes = [f"prompt sha256 {prompt_hash}"]
    if truncated:
        notes.append(f"prompt truncated to {len(snippets)}/{len(blocks)} blocks")
    if answer.value is None:
        return SlotResult(
            slot=slot,
            value=None,
            status="MISSING",
            method="llm",
            model=client.name,
            reason="; ".join(["model found no support", *notes]),
        )
    if bad or not answer.evidence_ids:
        notes.insert(0, f"invalid or no citations {bad}")
    else:
        cited = " ".join(norm(index.by_id[e].text) for e in answer.evidence_ids)
        notes.insert(
            0,
            "literal match in cited text"
            if norm(answer.value) in cited
            else "paraphrase: check against cited text",
        )
    return SlotResult(
        slot=slot,
        value=answer.value,
        status="NEEDS_REVIEW",
        method="llm",
        evidence_ids=[e for e in answer.evidence_ids if e in allowed],
        model=client.name,
        reason="; ".join(notes),
    )
