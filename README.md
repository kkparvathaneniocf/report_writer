# Laboratory Report AI — Ollama MVP

A runnable **first increment**, not a production-qualified laboratory reporting system.

## What works

- Ingest DOCX paragraphs/tables, text PDFs, CSV, XLSX, TXT/MD files with per-fragment locations and SHA-256.
- Extract cover metadata through an Ollama model using a Pydantic JSON schema.
- Deterministically calculate ISO 1172 style *reported* averages, sample SD, CV, extrema from standardized specimen CSV data. (The software does not implement or certify ISO 1172 test methods.)
- Record original cell evidence and identify LLM-generated fields requiring human review.
- Write a simple draft DOCX, or fill explicit `{{field_name}}` tokens in a supplied `.docx`.
- Export `report_data.json`, `evidence.json`, `statistics.json`, and `validation.json`.

## Install (Windows PowerShell / macOS / Linux)

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) (recommended) and Ollama running locally.

```bash
make install          # uv sync --extra dev (creates .venv from uv.lock)
make check            # format-check, lint, mypy, pytest
make ollama-setup     # pull the default model (gemma4:26b)
```

Without `make` (e.g. Windows): `python make.py install`, `python make.py ollama-setup`.
Without uv: `python -m venv .venv`, activate it, then `python -m pip install -e ".[dev]"`.

Dependencies are declared only in `pyproject.toml`; `uv.lock` pins the exact versions.

## Quick demo without Ollama

```bash
make demo             # copies examples/TR26_C0143_fiber.csv to data/raw and runs --skip-llm
```

## Run with Ollama

Place source documents in `data/raw` and run:

```bash
make run              # or: uv run lab-report run --model gemma4:26b
```

To populate explicit placeholders in your own DOCX:

```bash
lab-report run --template path/to/report_template.docx
```

The original document's text such as `Tasks: Product name...` is **not** automatically a placeholder. Add `{{product_name}}`, `{{test_requester}}`, `{{test_period}}`, `{{test_location}}` and/or `{{wf_percent_mean}}` to a test copy of the template.

## Important safety/quality limitations

1. The provided example data are test fixtures. They do not constitute independent verification of lab measurements.
2. LLM evidence references are checked for valid IDs only; factual consistency must be reviewed by personnel. Such fields are never auto-labelled VERIFIED.
3. The current RAG prototype uses lexical ranking (not a vector database) and at most 30 fragments; PDFs are text-only and scanned documents require a separate OCR pipeline.
4. Original Word comments, tracked changes, complex figure numbering, and rich formatting preservation are **not yet implemented**. Token replacement can remove inline formatting within edited paragraphs; always operate on a copy.
5. CSV format is explicitly constrained to `Specimen,Wf,Vf,Density,Porosity`; real machine exports need parsers per equipment family.
6. When evidence is missing, never sign or release automatically. Human authorization is mandatory.
7. Do not expose Ollama on a public network when processing proprietary lab information.
8. Production implementation should add schema-aware DOCX anchors, source-type priority, source conflicts, stable passage IDs, a true RAG index if needed, and document-level review/approval.
