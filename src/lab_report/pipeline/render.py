"""Fill a tokenized DOCX template and annotate every value with its provenance."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Cm

from lab_report.pipeline.docx_utils import (
    TOKEN,
    clone_row_after,
    iter_paragraphs,
    iter_tables,
    replace_text,
    row_paragraphs,
)
from lab_report.pipeline.images import IMAGE_PREFIX
from lab_report.pipeline.index import Index
from lab_report.pipeline.models import RowGroup, SlotResult

AUTHOR, INITIALS = "lab-report pipeline", "LR"
HIGHLIGHT = {
    "VERIFIED": None,
    "COMPUTED": None,
    "NEEDS_REVIEW": WD_COLOR_INDEX.TURQUOISE,
    "CONFLICT": WD_COLOR_INDEX.PINK,
    "MISSING": WD_COLOR_INDEX.RED,
    "NOT_IMPLEMENTED": WD_COLOR_INDEX.RED,
}
ROW_TOKEN = re.compile(r"\{\{\s*(\w+)\[\]\.(\w+)\s*\}\}")
ROW_SLOT = re.compile(r"^(\w+)\[(\d+)\]\.\w+$")


def describe_evidence(ids: list[str], index: Index, limit: int = 3) -> list[str]:
    """Group evidence by file/page/table so long lists stay readable."""
    groups: Counter[str] = Counter()
    quotes: dict[str, str] = {}
    for eid in ids:
        b = index.by_id.get(eid)
        if b is None:
            continue
        key = f"{b.file} p.{b.page}" + (f" table {b.table}" if b.kind == "cell" else "")
        groups[key] += 1
        quotes.setdefault(key, f"“{b.text[:90]}” [{eid}]")
    lines = [
        f"{key}: {quotes[key]}" if n == 1 else f"{key}: {n} cells, e.g. {quotes[key]}"
        for key, n in groups.items()
    ]
    return lines[:limit] + ([f"(+{len(lines) - limit} more sources)"] if len(lines) > limit else [])


def comment_text(result: SlotResult, index: Index, row: dict[str, SlotResult] | None) -> str:
    if row is not None:
        evidence = [e for cell in row.values() for e in cell.evidence_ids]
        statuses = sorted({c.status for c in row.values()})
        head = f"[{'/'.join(statuses)}] row {result.slot.split('.')[0]} via {result.method}"
    else:
        evidence = result.evidence_ids
        head = f"[{result.status}] {result.slot} via {result.method}"
    parts = [head, *describe_evidence(evidence, index)]
    if result.inputs and row is None:
        shown = ", ".join(result.inputs[:3]) + (" …" if len(result.inputs) > 3 else "")
        parts.append(f"inputs: {shown}")
    if result.reason:
        parts.append(f"note: {result.reason}")
    if result.model:
        parts.append(f"model: {result.model}")
    return "\n".join(parts)


def _expand_row_groups(doc, groups: dict[str, RowGroup]) -> None:
    """Clone each template row containing {{group[].col}} once per data row."""
    for table in list(iter_tables(doc)):
        for row in list(table.rows):
            text = " ".join(p.text for p in row_paragraphs(row))
            names = {m.group(1) for m in ROW_TOKEN.finditer(text)}
            if not names:
                continue
            name = names.pop()
            n = max(1, len(groups[name].rows)) if name in groups else 1
            clones, anchor = [row], row
            for _ in range(n - 1):
                anchor = clone_row_after(row, anchor)
                clones.append(anchor)
            for i, clone in enumerate(clones):
                for p in row_paragraphs(clone):
                    while (m := ROW_TOKEN.search(p.text)) is not None:
                        replace_text(p, m.group(0), f"{{{{{m.group(1)}[{i}].{m.group(2)}}}}}")


def _lookup(slot: str, results: dict[str, SlotResult], groups: dict[str, RowGroup]) -> SlotResult:
    if slot in results:
        return results[slot]
    m = ROW_SLOT.match(slot)
    if m and m.group(1) in groups:
        reason = groups[m.group(1)].reason or "row not present in source"
    else:
        reason = "template token has no entry in the report spec"
    return SlotResult(slot=slot, value=None, status="MISSING", method="none", reason=reason)


def render(
    template: Path,
    dest: Path,
    results: dict[str, SlotResult],
    groups: dict[str, RowGroup],
    index: Index,
    image_widths: dict[str, float] | None = None,
) -> dict:
    doc = Document(str(template))
    _expand_row_groups(doc, groups)
    filled: list[str] = []
    commented_rows: set[str] = set()
    for p in iter_paragraphs(doc):
        while (m := TOKEN.search(p.text)) is not None:
            result = _lookup(m.group(1), results, groups)
            is_image = result.slot.startswith(IMAGE_PREFIX) and result.value is not None
            shown = "" if is_image else (result.value or f"[{result.status}]")
            run = replace_text(p, m.group(0), shown)
            if run is None:  # token text split oddly; leave it visible for the reviewer
                break
            if is_image:
                width = (image_widths or {}).get(result.slot, 15)
                run.add_picture(str(result.value), width=Cm(width))
            run.font.highlight_color = HIGHLIGHT[result.status]
            filled.append(result.slot)
            row_match = ROW_SLOT.match(result.slot)
            row_key = result.slot.split(".")[0] if row_match else None
            if row_key and row_key in commented_rows:
                continue
            row = None
            if row_match and row_match.group(1) in groups:
                rows = groups[row_match.group(1)].rows
                i = int(row_match.group(2))
                row = rows[i] if i < len(rows) else None
            if row_key:
                commented_rows.add(row_key)
            doc.add_comment(run, comment_text(result, index, row), AUTHOR, INITIALS)
    leftovers = [m.group(0) for p in iter_paragraphs(doc) for m in TOKEN.finditer(p.text)]
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dest))
    return {"filled_tokens": filled, "unfilled_tokens": leftovers}
