"""Orchestrate: register/index -> extract -> verify -> compute -> render -> provenance."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pymupdf
import yaml

from lab_report.pipeline.extract import (
    compute_format,
    compute_join,
    compute_specimen_ids,
    compute_stats,
    extract_kv,
    extract_table,
    verify,
)
from lab_report.pipeline.images import IMAGE_PREFIX, extract_image
from lab_report.pipeline.index import PARSER_VERSION, Index, build_index
from lab_report.pipeline.llm import LLMClient, extract_llm
from lab_report.pipeline.models import RowGroup, SlotResult
from lab_report.pipeline.render import render


def _check_keys(node: object, where: str = "spec") -> None:
    """YAML 1.1 turns keys like `no`, `yes`, `on` into booleans; refuse them."""
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                raise ValueError(f"{where}: key {key!r} is not a string (quote it in YAML)")
            _check_keys(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _check_keys(value, f"{where}[{i}]")


def load_spec(path: Path) -> dict:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    _check_keys(spec)
    return spec


def extract_all(
    spec: dict, index: Index, llm: LLMClient | None, image_dir: Path | None = None
) -> tuple[dict[str, SlotResult], dict[str, RowGroup]]:
    decimal_comma = spec.get("decimal_comma", False)
    groups = {name: extract_table(name, t, index) for name, t in spec.get("tables", {}).items()}
    results: dict[str, SlotResult] = {}
    for group in groups.values():
        for row in group.rows:
            for cell in row.values():
                results[cell.slot] = verify(cell, index)

    fields = spec.get("fields", {})
    deferred = []
    for slot, f in fields.items():
        method = f["method"]
        if method == "kv":
            results[slot] = verify(extract_kv(slot, f, index), index)
        elif method == "llm":
            results[slot] = verify(extract_llm(slot, f, index, llm), index)
        elif method == "join":
            results[slot] = compute_join(slot, f, groups)
        elif method == "not_implemented":
            results[slot] = SlotResult(
                slot=slot,
                value=None,
                status="NOT_IMPLEMENTED",
                method="none",
                reason=f.get("reason"),
            )
        elif method == "format":
            deferred.append((slot, f))
        else:
            raise ValueError(f"{slot}: unknown method {method!r}")
    for prefix, s in spec.get("stats", {}).items():
        for r in compute_stats(prefix, s, groups, decimal_comma):
            results[r.slot] = r
    for slot, f in deferred:
        results[slot] = compute_format(slot, f, results)
    if "specimen_ids" in spec:
        tr = results.get("tr_number") or SlotResult(
            slot="tr_number", value=None, status="MISSING", method="none"
        )
        ids = compute_specimen_ids(spec["specimen_ids"], groups, tr)
        groups[ids.name] = ids
        for row in ids.rows:
            for cell in row.values():
                results[cell.slot] = cell
    for name, img in spec.get("images", {}).items():
        if image_dir is None:
            raise ValueError("image slots need an image_dir")
        r = extract_image(name, img, index, image_dir)
        results[r.slot] = r
    return results, groups


def save_evidence_crops(index: Index, ids: set[str], folder: Path) -> dict[str, str]:
    """PNG crop of every cited block, so a reviewer sees the source without opening the PDF."""
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    by_doc: dict[str, list] = {}
    for eid in sorted(ids):
        b = index.by_id[eid]
        if b.kind == "page":  # the exported page image is already the evidence
            continue
        by_doc.setdefault(b.doc_sha256, []).append(b)
    for digest, blocks in by_doc.items():
        with pymupdf.open(index.paths[digest]) as pdf:
            for b in blocks:
                clip = pymupdf.Rect(b.bbox) + (-6, -4, 6, 4)
                pix = pdf[b.page - 1].get_pixmap(dpi=120, clip=clip)
                path = folder / f"{b.id.replace(':', '_')}.png"
                pix.save(path)
                out[b.id] = str(path)
    return out


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    spec_path: Path,
    template: Path | None = None,
    llm: LLMClient | None = None,
) -> dict:
    spec = load_spec(spec_path)
    template = template or Path(spec["template"])
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template} (run `lab-report build-template`)")
    pdfs = sorted(p for p in input_dir.rglob("*.pdf") if p.is_file())
    if not pdfs:
        raise FileNotFoundError(f"No PDFs in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    index = build_index(pdfs, spec["documents"])
    index.save(output_dir / "index.sqlite")

    results, groups = extract_all(spec, index, llm, output_dir / "images")
    widths = {IMAGE_PREFIX + n: i.get("width_cm", 15) for n, i in spec.get("images", {}).items()}
    render_info = render(template, output_dir / "report.docx", results, groups, index, widths)

    cited = {e for r in results.values() for e in r.evidence_ids}
    crops = save_evidence_crops(index, cited, output_dir / "evidence")
    used = set(render_info["filled_tokens"])
    slots = []
    for r in results.values():
        entry = r.model_dump()
        entry["in_report"] = r.slot in used
        entry["evidence"] = [
            {**index.by_id[e].model_dump(exclude={"doc_sha256"}), "crop": crops.get(e)}
            for e in r.evidence_ids
        ]
        slots.append(entry)
    counts = Counter(r.status for r in results.values() if r.slot in used)
    provenance = {
        "run": {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "spec": str(spec_path),
            "template": str(template),
            "parser": PARSER_VERSION,
            "llm": getattr(llm, "name", None),
        },
        "documents": index.documents,
        "status_counts": dict(counts),
        "unfilled_tokens": render_info["unfilled_tokens"],
        "manual_fields": spec.get("manual", []),
        "groups": {
            n: {"rows": len(g.rows), "status": g.status, "reason": g.reason}
            for n, g in groups.items()
        },
        "slots": slots,
    }
    (output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return provenance
