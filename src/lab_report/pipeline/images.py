"""Image slots: page snapshots, embedded photos and vector figures, exported as PNG with
provenance (source block id + SHA-256 of the exported picture)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf

from lab_report.pipeline.extract import norm
from lab_report.pipeline.index import Index
from lab_report.pipeline.models import Block, SlotResult

IMAGE_PREFIX = "image:"


def _select(spec: dict, index: Index) -> tuple[list[Block], str]:
    blocks = index.of_type(spec["source"])
    if spec["method"] == "page":
        page = spec.get("page", 1)
        return [b for b in blocks if b.kind == "page" and b.page == page], f"page {page}"
    kinds = {"figure": ("image", "figure"), "image": ("image",)}[spec["method"]]
    caption = norm(spec["caption"])
    return (
        [b for b in blocks if b.kind in kinds and caption in norm(b.text)],
        f"caption containing '{spec['caption']}'",
    )


def extract_image(name: str, spec: dict, index: Index, folder: Path) -> SlotResult:
    slot = IMAGE_PREFIX + name
    matches, wanted = _select(spec, index)
    if not matches:
        return SlotResult(
            slot=slot,
            value=None,
            status="MISSING",
            method=spec["method"],
            reason=f"no {spec['source']} visual with {wanted}",
        )
    block = matches[0]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    with pymupdf.open(index.paths[block.doc_sha256]) as pdf:
        page = pdf[block.page - 1]
        clip = None if block.kind == "page" else pymupdf.Rect(block.bbox) + (-4, -4, 4, 4)
        page.get_pixmap(dpi=spec.get("dpi", 150), clip=clip).save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    notes = [f"{block.kind} matched by {wanted}", f"png sha256 {digest[:16]}"]
    if len(matches) > 1:
        notes.append(f"{len(matches)} candidates, first used: {[m.id for m in matches]}")
    return SlotResult(
        slot=slot,
        value=str(path),
        status="VERIFIED" if len(matches) == 1 else "NEEDS_REVIEW",
        method=spec["method"],
        evidence_ids=[block.id],
        reason="; ".join(notes),
    )
