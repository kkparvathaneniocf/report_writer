"""Register source PDFs and index them into addressable blocks (lines + table cells).

Block IDs are stable for identical file bytes and parser version:
    <sha256[:8]>:p<page>:l<line>          text line
    <sha256[:8]>:p<page>:t<table>r<row>c<col>   table cell
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from pathlib import Path

import pymupdf

from lab_report.pipeline.models import Block

PARSER_VERSION = f"pymupdf-{pymupdf.__version__}/pages+lines+cells+visuals-v2"
# Default flags minus ligature preservation, so "fi" is not returned as U+FB01.
TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(path: Path, first_page_text: str, rules: dict[str, dict]) -> tuple[str, str]:
    """Return (doc_type, how). Filename rules first, then first-page keywords."""
    name = path.name.lower()
    for doc_type, rule in rules.items():
        if any(k.lower() in name for k in rule.get("filename", [])):
            return doc_type, "filename"
    text = first_page_text.lower()
    for doc_type, rule in rules.items():
        if any(k.lower() in text for k in rule.get("keywords", [])):
            return doc_type, "keyword"
    return "UNKNOWN", "none"


def _cell_text(words: list[tuple], bbox: tuple) -> str:
    """Join words whose centre lies in bbox. More robust than Table.extract(), which splits
    underscores off identifiers such as TR26_C0143_01_1."""
    x0, y0, x1, y1 = bbox
    inside = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    inside.sort(key=lambda w: (w[5], w[6], w[7]))  # block, line, word number
    lines: dict[tuple, list[str]] = {}
    for w in inside:
        lines.setdefault((w[5], w[6]), []).append(w[4])
    return " ".join(" ".join(ws) for ws in lines.values())


def parse_pdf(path: Path, digest: str, doc_type: str) -> list[Block]:
    blocks: list[Block] = []
    short = digest[:8]
    with pymupdf.open(path) as pdf:
        for page_no, page in enumerate(pdf, 1):
            first_line = page.get_text(flags=TEXT_FLAGS).strip().split("\n")[0][:120]
            blocks.append(
                Block(
                    id=f"{short}:p{page_no}",
                    doc_sha256=digest,
                    file=path.name,
                    doc_type=doc_type,
                    page=page_no,
                    kind="page",
                    bbox=tuple(round(v, 1) for v in page.rect),
                    text=f"page {page_no}/{pdf.page_count}: {first_line}",
                )
            )
            page_start = len(blocks)
            line_no = 0
            for b in page.get_text("dict", flags=TEXT_FLAGS)["blocks"]:
                for line in b.get("lines", []):
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    if not text:
                        continue
                    line_no += 1
                    blocks.append(
                        Block(
                            id=f"{short}:p{page_no}:l{line_no}",
                            doc_sha256=digest,
                            file=path.name,
                            doc_type=doc_type,
                            page=page_no,
                            kind="line",
                            bbox=tuple(round(v, 1) for v in line["bbox"]),
                            text=text,
                        )
                    )
            words = page.get_text("words", flags=TEXT_FLAGS)
            tables = page.find_tables().tables
            for t_no, table in enumerate(tables, 1):
                for r_no, row in enumerate(table.rows):
                    for c_no, bbox in enumerate(row.cells):
                        if bbox is None:  # merged cell
                            continue
                        blocks.append(
                            Block(
                                id=f"{short}:p{page_no}:t{t_no}r{r_no}c{c_no}",
                                doc_sha256=digest,
                                file=path.name,
                                doc_type=doc_type,
                                page=page_no,
                                kind="cell",
                                bbox=tuple(round(v, 1) for v in bbox),
                                text=_cell_text(words, bbox),
                                table=t_no,
                                row=r_no,
                                col=c_no,
                            )
                        )
            lines = [b for b in blocks[page_start:] if b.kind == "line"]
            visuals = _images(page) + _figures(page, [pymupdf.Rect(t.bbox) for t in tables])
            for n, (kind, rect, xref) in enumerate(visuals, 1):
                caption_lines = lines
                if kind == "figure":
                    rect, absorbed = _absorb_labels(rect, lines)
                    caption_lines = [b for b in lines if b.id not in absorbed]
                blocks.append(
                    Block(
                        id=f"{short}:p{page_no}:{kind[0]}{n}",
                        doc_sha256=digest,
                        file=path.name,
                        doc_type=doc_type,
                        page=page_no,
                        kind=kind,
                        bbox=tuple(round(v, 1) for v in rect),
                        text=_caption(rect, caption_lines),
                        xref=xref,
                    )
                )
    return blocks


def _images(page: pymupdf.Page) -> list[tuple[str, pymupdf.Rect, int | None]]:
    """Embedded raster images (photos, screenshots) with their position on the page."""
    out: list[tuple[str, pymupdf.Rect, int | None]] = []
    for info in page.get_images(full=True):
        for rect in page.get_image_rects(info[0]):
            if rect.width > 40 and rect.height > 40:  # skip icons and logos
                out.append(("image", rect, info[0]))
    return out


def _figures(page: pymupdf.Page, tables: list[pymupdf.Rect]) -> list[tuple]:
    """Vector graphics regions (plotted curves, diagrams) that are not table rulings.

    Machine software usually draws stress/strain curves as vector paths, so image
    extraction alone would miss them.
    """
    out = []
    for rect in page.cluster_drawings():
        if rect.width < 120 or rect.height < 80:
            continue
        if any(abs(rect & t) > 0.5 * abs(rect) for t in tables):
            continue
        out.append(("figure", rect, None))
    return out


def _absorb_labels(rect: pymupdf.Rect, lines: list[Block]) -> tuple[pymupdf.Rect, set[str]]:
    """Grow a vector figure's box over its axis labels (short text lines touching it)."""
    zone = rect + (-40, -15, 15, 30)
    grown, absorbed = pymupdf.Rect(rect), set()
    for b in lines:
        r = pymupdf.Rect(b.bbox)
        if zone.intersects(r) and len(b.text) <= 20:
            grown |= r
            absorbed.add(b.id)
    return grown, absorbed


def _caption(rect: pymupdf.Rect, lines: list[Block], gap: float = 30) -> str:
    """Nearest text line just below (preferred) or above a visual, overlapping horizontally."""

    def overlaps(b: Block) -> bool:
        return b.bbox[0] < rect.x1 and b.bbox[2] > rect.x0

    below = [b for b in lines if overlaps(b) and 0 <= b.bbox[1] - rect.y1 <= gap]
    above = [b for b in lines if overlaps(b) and 0 <= rect.y0 - b.bbox[3] <= gap]
    if below:
        return min(below, key=lambda b: b.bbox[1]).text
    if above:
        return max(above, key=lambda b: b.bbox[3]).text
    return ""


class Index:
    """In-memory view of all indexed blocks, persisted to SQLite for audit."""

    def __init__(self, documents: list[dict], blocks: list[Block]):
        self.documents = documents
        self.blocks = blocks
        self.by_id = {b.id: b for b in blocks}
        self.paths = {d["sha256"]: Path(d["path"]) for d in documents}

    def lines(self, doc_type: str) -> list[Block]:
        return [b for b in self.blocks if b.doc_type == doc_type and b.kind == "line"]

    def cells(self, doc_type: str) -> list[Block]:
        return [b for b in self.blocks if b.doc_type == doc_type and b.kind == "cell"]

    def of_type(self, doc_type: str) -> list[Block]:
        return [b for b in self.blocks if b.doc_type == doc_type]

    def save(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.unlink(missing_ok=True)
        with sqlite3.connect(db_path) as con:
            con.executescript(
                """
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE documents(sha256 TEXT PRIMARY KEY, file TEXT, path TEXT,
                    doc_type TEXT, classified_by TEXT, pages INTEGER);
                CREATE TABLE blocks(id TEXT PRIMARY KEY, doc_sha256 TEXT REFERENCES documents,
                    page INTEGER, kind TEXT, tbl INTEGER, row INTEGER, col INTEGER,
                    x0 REAL, y0 REAL, x1 REAL, y1 REAL, text TEXT, xref INTEGER);
                """
            )
            con.execute("INSERT INTO meta VALUES ('parser_version', ?)", (PARSER_VERSION,))
            con.executemany(
                "INSERT INTO documents VALUES (:sha256, :file, :path, :doc_type, "
                ":classified_by, :pages)",
                self.documents,
            )
            con.executemany(
                "INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        b.id,
                        b.doc_sha256,
                        b.page,
                        b.kind,
                        b.table,
                        b.row,
                        b.col,
                        *b.bbox,
                        b.text,
                        b.xref,
                    )
                    for b in self.blocks
                ],
            )


def build_index(paths: Iterable[Path], rules: dict[str, dict]) -> Index:
    documents: list[dict] = []
    blocks: list[Block] = []
    for path in sorted(paths):
        digest = sha256(path)
        with pymupdf.open(path) as pdf:
            first = pdf[0].get_text(flags=TEXT_FLAGS) if pdf.page_count else ""
            pages = pdf.page_count
        doc_type, how = classify(path, first, rules)
        documents.append(
            {
                "sha256": digest,
                "file": path.name,
                "path": str(path.resolve()),
                "doc_type": doc_type,
                "classified_by": how,
                "pages": pages,
            }
        )
        if doc_type != "UNKNOWN":
            blocks.extend(parse_pdf(path, digest, doc_type))
    return Index(documents, blocks)
