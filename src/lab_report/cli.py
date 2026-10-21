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
    stats = {}
    csvs = list(input_dir.rglob("*fiber*.csv")) if input_dir.exists() else []
    if csvs:
        fiber_output, fiber_evidence, stats = calculate_fiber_content(csvs[0])
        outputs.append(fiber_output)
        evidence.extend(fiber_evidence)
    if not skip_llm:
        fragments = ingest_folder(input_dir)
        if fragments:
            metadata_output, metadata_evidence = extract_section(
                "cover", ["test_requester", "test_period", "product_name", "test_location"],
                fragments, model=model, host=host)
            outputs.append(metadata_output)
            # Prefix ids to avoid collisions with fiber's distinct F... ids.
            evidence.extend(metadata_evidence)
    if not outputs:
        typer.echo("No supported data found. Add a *fiber*.csv or source documents.", err=True)
        raise typer.Exit(1)
    dump(output_dir / "report_data.json", [o.model_dump() for o in outputs])
    dump(output_dir / "evidence.json", [e.model_dump() for e in evidence])
    dump(output_dir / "statistics.json", stats)
    dump(output_dir / "validation.json", {"requires_human_review": [
        {"section": o.section_id, "field": f.field_name, "status": f.status}
        for o in outputs for f in o.fields if f.status != "VERIFIED"]})
    write_report(outputs, output_dir / "report.docx", template)
    typer.echo(f"Saved report and evidence manifest under {output_dir}")


if __name__ == "__main__":
    app()
