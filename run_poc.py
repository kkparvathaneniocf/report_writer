"""Generate the POC Word report from dummy PDFs. No make, no uv needed.

Setup once (any OS):
    python -m venv .venv
    .venv\\Scripts\\activate          (Windows)   |   source .venv/bin/activate   (macOS/Linux)
    python -m pip install -e ".[dev]"

Run:
    python run_poc.py                       # without LLM (AI fields reported MISSING)
    python run_poc.py --llm                 # with Gemma via Ollama (must be running)
    python run_poc.py --llm --model gemma4:12b

Or from Python:
    from run_poc import generate_poc_report
    generate_poc_report()
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))  # works even if the package is not pip-installed

from lab_report.pipeline.dummy import make_dummy_tr_folder  # noqa: E402
from lab_report.pipeline.run import run_pipeline  # noqa: E402
from lab_report.pipeline.template_builder import build_template  # noqa: E402

DNV_TEMPLATE = ROOT / "data" / "templet" / "DNV report_description for agents AI.docx"
SPEC = ROOT / "config" / "report_spec.yaml"


def generate_poc_report(
    tr: str = "TR26_C0143",
    use_llm: bool = False,
    model: str = "gemma4:26b",
    host: str = "http://localhost:11434",
) -> Path:
    """Create dummy PDFs, tokenize the DNV template, fill it, and return the report path.

    Outputs in output/<tr>/: report.docx, provenance.json, index.sqlite, evidence/*.png
    """
    input_dir = ROOT / "data" / "raw" / tr
    output_dir = ROOT / "output" / tr
    template = ROOT / "data" / "templet" / "dnv_poc_template.docx"

    print(f"1/3 Generating dummy PDFs in {input_dir}")
    for pdf in make_dummy_tr_folder(input_dir):
        print(f"      {pdf.name}")

    print(f"2/3 Building tokenized template from {DNV_TEMPLATE.name}")
    build_template(DNV_TEMPLATE, template)

    llm = None
    if use_llm:
        from lab_report.pipeline.llm import OllamaClient

        llm = OllamaClient(model, host)
    print(f"3/3 Extracting and writing report ({llm.name if llm else 'no LLM'})")
    prov = run_pipeline(input_dir, output_dir, SPEC, template, llm)

    print(f"\nStatus of values in the report: {prov['status_counts']}")
    for slot in prov["slots"]:
        if slot["in_report"] and slot["status"] not in ("VERIFIED", "COMPUTED"):
            print(f"  {slot['status']:<15} {slot['slot']:<24} {slot['reason'] or ''}")
    if prov["unfilled_tokens"]:
        print(f"Unfilled template tokens: {prov['unfilled_tokens']}")
    report = output_dir / "report.docx"
    print(f"\nReport:     {report}")
    print(f"Provenance: {output_dir / 'provenance.json'}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the POC Word report from dummy PDFs.")
    parser.add_argument("--tr", default="TR26_C0143", help="TR folder name")
    parser.add_argument("--llm", action="store_true", help="Use Gemma via Ollama")
    parser.add_argument("--model", default="gemma4:26b")
    parser.add_argument("--host", default="http://localhost:11434")
    args = parser.parse_args()
    generate_poc_report(args.tr, args.llm, args.model, args.host)
