"""Deterministic extractors and calculations. Every output cites block ids or input slots."""

from __future__ import annotations

import re
import statistics

from lab_report.pipeline.index import Index
from lab_report.pipeline.models import Block, RowGroup, SlotResult, Status


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def parse_number(text: str) -> float:
    return float(text.strip().replace(" ", "").replace(",", "."))


def fmt_number(value: float, decimals: int, decimal_comma: bool) -> str:
    out = f"{value:.{decimals}f}"
    return out.replace(".", ",") if decimal_comma else out


# --------------------------------------------------------------------------- key/value


def find_kv(index: Index, source: str, label: str, pattern: str | None = None) -> list[tuple]:
    """All (value, block) hits for `label` in documents of type `source`.

    Matches "Label: value" lines, and a label cell followed by a value cell in the same row.
    """
    hits: list[tuple[str, Block]] = []
    line_re = re.compile(rf"^\s*{re.escape(label)}\s*[:=]\s*(.+?)\s*$", re.IGNORECASE)
    for b in index.lines(source):
        m = line_re.match(b.text)
        if m:
            hits.append((m.group(1), b))
    cells = index.cells(source)
    for b in cells:
        if norm(b.text).rstrip(":") == norm(label):
            right = next(
                (
                    c
                    for c in cells
                    if c.doc_sha256 == b.doc_sha256
                    and (c.page, c.table, c.row) == (b.page, b.table, b.row)
                    and c.col == (b.col or 0) + 1
                ),
                None,
            )
            if right and right.text:
                hits.append((right.text, right))
    if pattern:
        hits = [(m.group(1), b) for v, b in hits if (m := re.search(pattern, v))]
    return hits


def extract_kv(slot: str, spec: dict, index: Index) -> SlotResult:
    hits = find_kv(index, spec["source"], spec["label"], spec.get("pattern"))
    if not hits:
        return SlotResult(
            slot=slot,
            value=None,
            status="MISSING",
            method="kv",
            reason=f"label '{spec['label']}' not found in any {spec['source']} document",
        )
    values = {v for v, _ in hits}
    evidence = [b.id for _, b in hits]
    if len(values) > 1:
        return SlotResult(
            slot=slot,
            value=hits[0][0],
            status="CONFLICT",
            method="kv",
            evidence_ids=evidence,
            reason=f"different values within {spec['source']}: {sorted(values)}",
        )
    value = hits[0][0]
    for check in spec.get("cross_check", []):
        other = find_kv(index, check["source"], check["label"], spec.get("pattern"))
        evidence += [b.id for _, b in other]
        mismatched = {v for v, _ in other if norm(v) != norm(value)}
        if mismatched:
            return SlotResult(
                slot=slot,
                value=value,
                status="CONFLICT",
                method="kv",
                evidence_ids=evidence,
                reason=(
                    f"{spec['source']} says '{value}' but {check['source']} "
                    f"'{check['label']}' says {sorted(mismatched)}"
                ),
            )
    return SlotResult(slot=slot, value=value, status="VERIFIED", method="kv", evidence_ids=evidence)


# --------------------------------------------------------------------------- tables


def extract_table(name: str, spec: dict, index: Index) -> RowGroup:
    """Rows of the first table (in the source doc type) whose header contains all column
    labels and none of `exclude_headers`."""
    cells = index.cells(spec["source"])
    tables: dict[tuple, list[Block]] = {}
    for c in cells:
        tables.setdefault((c.doc_sha256, c.page, c.table), []).append(c)
    wanted = spec["columns"]
    excluded = [norm(h) for h in spec.get("exclude_headers", [])]
    for table_cells in tables.values():
        header = {c.col: norm(c.text) for c in table_cells if c.row == 0}
        if any(x in h for h in header.values() for x in excluded):
            continue
        col_of: dict[str, int] = {}
        for key, label in wanted.items():
            col = next((i for i, h in header.items() if norm(label) in h), None)
            if col is None:
                break
            col_of[key] = col
        else:
            grid = {(c.row, c.col): c for c in table_cells}
            n_rows = max(c.row or 0 for c in table_cells)
            group = RowGroup(name=name)
            for r in range(1, n_rows + 1):
                row: dict[str, SlotResult] = {}
                for key, col in col_of.items():
                    cell = grid.get((r, col))
                    row[key] = SlotResult(
                        slot=f"{name}[{r - 1}].{key}",
                        value=cell.text if cell and cell.text else None,
                        status="VERIFIED" if cell and cell.text else "MISSING",
                        method="table",
                        evidence_ids=[cell.id] if cell else [],
                    )
                for key, rule in spec.get("derive", {}).items():
                    src = row[rule["from"]]
                    m = re.search(rule["regex"], src.value or "")
                    row[key] = SlotResult(
                        slot=f"{name}[{r - 1}].{key}",
                        value=m.group(1) if m else None,
                        status=src.status if m else "MISSING",
                        method="table",
                        evidence_ids=src.evidence_ids,
                        reason=f"derived from {rule['from']} with /{rule['regex']}/",
                    )
                group.rows.append(row)
            return group
    return RowGroup(
        name=name,
        status="MISSING",
        reason=f"no {spec['source']} table with headers {list(wanted.values())}",
    )


# --------------------------------------------------------------------------- calculations


def _combined_status(parts: list[SlotResult]) -> Status:
    statuses = {p.status for p in parts}
    if "MISSING" in statuses:
        return "MISSING"
    if "CONFLICT" in statuses:
        return "CONFLICT"
    return "NEEDS_REVIEW" if "NEEDS_REVIEW" in statuses else "COMPUTED"


def compute_stats(
    prefix: str, spec: dict, groups: dict[str, RowGroup], decimal_comma: bool
) -> list[SlotResult]:
    group = groups[spec["table"]]
    out: list[SlotResult] = []
    out.append(
        SlotResult(
            slot=f"{prefix}.count",
            value=str(len(group.rows)) if group.rows else None,
            status="COMPUTED" if group.rows else "MISSING",
            method="stats",
            inputs=[f"{group.name}[*]"],
            reason=group.reason,
        )
    )
    for column, decimals in spec["columns"].items():
        cells = [row[column] for row in group.rows]
        base = f"{prefix}.{column}"
        try:
            values = [parse_number(c.value or "") for c in cells]
        except ValueError as exc:
            out += [
                SlotResult(
                    slot=f"{base}.{op}",
                    value=None,
                    status="MISSING",
                    method="stats",
                    inputs=[c.slot for c in cells],
                    reason=f"non-numeric input: {exc}",
                )
                for op in ("mean", "sd", "cv", "max", "min")
            ]
            continue
        if len(values) < 2:
            reason = "fewer than 2 specimens" if group.rows else group.reason
            out += [
                SlotResult(
                    slot=f"{base}.{op}", value=None, status="MISSING", method="stats", reason=reason
                )
                for op in ("mean", "sd", "cv", "max", "min")
            ]
            continue
        mean = statistics.fmean(values)
        sd = statistics.stdev(values)
        results = {
            "mean": fmt_number(mean, decimals, decimal_comma),
            "sd": fmt_number(sd, decimals, decimal_comma),
            # CV in percent (template example shows a fraction; confirm with the lab).
            "cv": fmt_number(sd / abs(mean) * 100, 2, decimal_comma) if mean else None,
            "max": fmt_number(max(values), decimals, decimal_comma),
            "min": fmt_number(min(values), decimals, decimal_comma),
        }
        status = _combined_status(cells)
        for op, value in results.items():
            out.append(
                SlotResult(
                    slot=f"{base}.{op}",
                    value=value,
                    status=status if value is not None else "MISSING",
                    method="stats",
                    inputs=[c.slot for c in cells],
                    evidence_ids=[e for c in cells for e in c.evidence_ids],
                    reason=f"{op} of n={len(values)}, sample SD (n-1)"
                    + (", CV in %" if op == "cv" else ""),
                )
            )
    return out


def compute_join(slot: str, spec: dict, groups: dict[str, RowGroup]) -> SlotResult:
    group = groups[spec["table"]]
    if not group.rows:
        return SlotResult(
            slot=slot, value=None, status="MISSING", method="join", reason=group.reason
        )
    parts = [c for row in group.rows for c in row.values()]
    lines = [spec["row"].format(**{k: c.value or "" for k, c in row.items()}) for row in group.rows]
    return SlotResult(
        slot=slot,
        value=spec.get("sep", "\n").join(lines),
        status=_combined_status(parts),
        method="join",
        inputs=[c.slot for c in parts],
        evidence_ids=[e for c in parts for e in c.evidence_ids],
    )


def compute_format(slot: str, spec: dict, results: dict[str, SlotResult]) -> SlotResult:
    names = re.findall(r"\{(\w+)\}", spec["template"])
    parts = [results[n] for n in names]
    if any(p.value is None for p in parts):
        return SlotResult(
            slot=slot,
            value=None,
            status="MISSING",
            method="format",
            inputs=names,
            reason="an input slot is missing",
        )
    return SlotResult(
        slot=slot,
        value=spec["template"].format(**{n: results[n].value for n in names}),
        status=_combined_status(parts),
        method="format",
        inputs=names,
        evidence_ids=[e for p in parts for e in p.evidence_ids],
    )


def compute_specimen_ids(
    entries: list[dict], groups: dict[str, RowGroup], tr: SlotResult
) -> RowGroup:
    out = RowGroup(name="specimen_ids")
    for i, entry in enumerate(entries):
        group = groups[entry["table"]]
        cells = [row[entry["column"]] for row in group.rows]
        if not cells:
            continue
        refs = f"{cells[0].value} … {cells[-1].value}" if len(cells) > 1 else cells[0].value
        evidence = [e for c in cells for e in c.evidence_ids]
        status = _combined_status([*cells, tr])
        columns: list[tuple[str, str | None, Status, list[str]]] = [
            ("tr", tr.value, tr.status, tr.evidence_ids),
            ("refs", refs, status, evidence),
            ("test", entry["test"], "COMPUTED", []),
            ("direction", entry["direction"], "COMPUTED", []),
            ("count", str(len(cells)), status, evidence),
        ]
        out.rows.append(
            {
                key: SlotResult(
                    slot=f"specimen_ids[{i}].{key}",
                    value=value,
                    status=st,
                    method="compute",
                    evidence_ids=ev,
                    inputs=[c.slot for c in cells],
                )
                for key, value, st, ev in columns
            }
        )
    return out


# --------------------------------------------------------------------------- verification


def verify(result: SlotResult, index: Index) -> SlotResult:
    """Re-check deterministic results against the cited block text."""
    unknown = [e for e in result.evidence_ids if e not in index.by_id]
    if unknown:
        result.status = "NEEDS_REVIEW"
        result.reason = f"cites unknown block ids {unknown}"
    elif result.status == "VERIFIED" and result.value is not None:
        texts = [norm(index.by_id[e].text) for e in result.evidence_ids]
        if not any(norm(result.value) in t for t in texts):
            result.status = "NEEDS_REVIEW"
            result.reason = "value not found literally in cited source"
    return result
