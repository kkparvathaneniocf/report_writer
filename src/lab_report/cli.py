from __future__ import annotations

import json
from pathlib import Path

import typer

from lab_report.agents.extractor import extract_section
from lab_report.agents.fiber_content import calculate_fiber_content
from lab_report.generation.writer import write_report
from lab_report.ingestion.readers import ingest_folder

app = typer.Typer(help="Local, traceable laboratory report prototype")


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


@app.command()
def inspect(input_dir: Path = typer.Option(Path("data/raw"))) -> None:
    """List indexed fragments before running the report."""
    for fragment in ingest_folder(input_dir):
        typer.echo(f"{fragment.source_file} {fragment.location}: {fragment.text[:100]}")


@app.command()
def run(
    input_dir: Path = typer.Option(Path("data/raw"), help="Folder of supporting documents"),
    output_dir: Path = typer.Option(Path("output")),
    template: Path | None = typer.Option(None, help="Optional .docx with {{field_name}} tokens"),
    model: str = typer.Option("gemma4:26b"),
    host: str = typer.Option("http://localhost:11434"),
    skip_llm: bool = typer.Option(False, help="Use only deterministic CSV fiber calculations"),
) -> None:
    if template and not template.exists():
        raise typer.BadParameter(f"Template not found: {template}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    evidence = []
    stats: dict = {}
    csvs = list(input_dir.rglob("*fiber*.csv")) if input_dir.exists() else []
    if csvs:
        fiber_output, fiber_evidence, stats = calculate_fiber_content(csvs[0])
        outputs.append(fiber_output)
        evidence.extend(fiber_evidence)
    if not skip_llm:
        fragments = ingest_folder(input_dir)
        if fragments:
            metadata_output, metadata_evidence = extract_section(
                "cover",
                ["test_requester", "test_period", "product_name", "test_location"],
                fragments,
                model=model,
                host=host,
            )
            outputs.append(metadata_output)
            # Prefix ids to avoid collisions with fiber's distinct F... ids.
            evidence.extend(metadata_evidence)
    if not outputs:
        typer.echo("No supported data found. Add a *fiber*.csv or source documents.", err=True)
        raise typer.Exit(1)
    dump(output_dir / "report_data.json", [o.model_dump() for o in outputs])
    dump(output_dir / "evidence.json", [e.model_dump() for e in evidence])
    dump(output_dir / "statistics.json", stats)
    dump(
        output_dir / "validation.json",
        {
            "requires_human_review": [
                {"section": o.section_id, "field": f.field_name, "status": f.status}
                for o in outputs
                for f in o.fields
                if f.status != "VERIFIED"
            ]
        },
    )
    write_report(outputs, output_dir / "report.docx", template)
    typer.echo(f"Saved report and evidence manifest under {output_dir}")


# --------------------------------------------------------------------------- PDF pipeline POC

DNV_SOURCE = Path("data/templet/DNV report_description for agents AI.docx")
DNV_TOKENIZED = Path("data/templet/dnv_poc_template.docx")
SPEC = Path("config/report_spec.yaml")


@app.command("make-dummy")
def make_dummy(folder: Path = typer.Option(Path("data/raw/TR26_C0143"))) -> None:
    """Generate a fake TR folder of PDFs (with one planted conflict and one missing value)."""
    from lab_report.pipeline.dummy import make_dummy_tr_folder

    for path in make_dummy_tr_folder(folder):
        typer.echo(f"wrote {path}")


@app.command("build-template")
def build_template_cmd(
    source: Path = typer.Option(DNV_SOURCE), dest: Path = typer.Option(DNV_TOKENIZED)
) -> None:
    """Convert the DNV report description into a tokenized template."""
    from lab_report.pipeline.template_builder import build_template

    typer.echo(f"wrote {build_template(source, dest)}")


@app.command()
def report(
    input_dir: Path = typer.Option(Path("data/raw/TR26_C0143"), help="TR folder with PDFs"),
    output_dir: Path = typer.Option(Path("output/TR26_C0143")),
    spec: Path = typer.Option(SPEC),
    template: Path | None = typer.Option(None, help="Defaults to the template in the spec"),
    model: str = typer.Option("gemma4:26b"),
    host: str = typer.Option("http://localhost:11434"),
    no_llm: bool = typer.Option(False, help="Skip LLM fields (they are reported MISSING)"),
) -> None:
    """Build report.docx + provenance.json + index.sqlite + evidence crops from PDFs."""
    from lab_report.pipeline.llm import OllamaClient
    from lab_report.pipeline.run import run_pipeline

    llm = None if no_llm else OllamaClient(model, host)
    prov = run_pipeline(input_dir, output_dir, spec, template, llm)
    for doc in prov["documents"]:
        typer.echo(f"  {doc['doc_type']:<16} {doc['file']}  ({doc['classified_by']})")
    typer.echo(f"Status of values placed in the report: {prov['status_counts']}")
    for s in prov["slots"]:
        if s["in_report"] and s["status"] not in ("VERIFIED", "COMPUTED"):
            typer.echo(f"  {s['status']:<15} {s['slot']:<28} {s['reason'] or ''}")
    if prov["unfilled_tokens"]:
        typer.echo(f"Unfilled template tokens: {prov['unfilled_tokens']}", err=True)
    typer.echo(f"Manual fields still to enter: {', '.join(prov['manual_fields'])}")
    typer.echo(f"Output: {output_dir}")


@app.command()
def trace(
    slot: str = typer.Argument(..., help="Slot name, e.g. fabric_batch or fwf.wf.mean"),
    output_dir: Path = typer.Option(Path("output/TR26_C0143")),
) -> None:
    """Show where a report value came from."""
    prov = json.loads((output_dir / "provenance.json").read_text(encoding="utf-8"))
    by_slot = {s["slot"]: s for s in prov["slots"]}
    if slot not in by_slot:
        close = [s for s in by_slot if slot in s][:10]
        raise typer.BadParameter(f"unknown slot {slot!r}. Similar: {close}")
    s = by_slot[slot]
    typer.echo(f"{s['slot']} = {s['value']!r}  [{s['status']}] via {s['method']}")
    if s["reason"]:
        typer.echo(f"  note: {s['reason']}")
    if s["model"]:
        typer.echo(f"  model: {s['model']}")
    if s["inputs"]:
        typer.echo(f"  inputs: {', '.join(s['inputs'])}")
    for e in s["evidence"]:
        typer.echo(f"  ← {e['file']} p.{e['page']} bbox={e['bbox']} [{e['id']}]")
        typer.echo(f"      “{e['text']}”  crop: {e['crop']}")


if __name__ == "__main__":
    app()
