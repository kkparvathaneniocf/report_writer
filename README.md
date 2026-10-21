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

Requires Python 3.11+ and, for LLM fields, Ollama running locally. No `make` or `uv` needed.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
python -m pip install -e ".[dev]"
python -m pytest -q
```

`python make.py <command>` wraps common tasks (`install`, `check`, `poc`, `poc-llm`, `trace`,
`ollama-setup`, ...; see `python make.py --help`). It uses uv when installed, else `.venv`.
Dependencies are declared only in `pyproject.toml`; `uv.lock` pins exact versions for uv users.

## Quick demo without Ollama

```bash
python make.py demo   # copies examples/TR26_C0143_fiber.csv to data/raw and runs --skip-llm
```

## PDF pipeline POC (dummy data)

End-to-end check of the target architecture on generated PDFs that mimic a TR folder
(test request, FWF file, tensile machine report, fabric COA, infusion report):

```bash
python run_poc.py                       # no LLM: LLM fields are reported MISSING
python run_poc.py --llm                 # with Gemma via Ollama (default gemma4:26b)
python run_poc.py --llm --model gemma4:12b
lab-report trace fabric_batch           # where did a value come from?
```

Output in `output/TR26_C0143/`: `report.docx`, `provenance.json`, `index.sqlite`, `evidence/*.png`.

Needs `data/templet/DNV report_description for agents AI.docx`; `build-template` turns it into
`data/templet/dnv_poc_template.docx` with `{{slot}}` tokens.

```
PDFs ─► register+classify ─► index (lines + table cells, stable ids, bbox) ─► index.sqlite
     ─► extract per config/report_spec.yaml (kv | table | llm) ─► verify against cited text
     ─► compute (stats, joins) ─► render DOCX (Word comment per value) ─► provenance.json
                                                                       ─► evidence/*.png crops
```

Every value carries a status: `VERIFIED` (found literally in the cited block), `COMPUTED`,
`NEEDS_REVIEW` (LLM output), `CONFLICT` (sources disagree), `MISSING`, `NOT_IMPLEMENTED`.
In the DOCX, non-verified values are highlighted (turquoise review, pink conflict, red missing).
The dummy data plants a fabric-batch conflict (COA vs infusion report) and a missing catalyst
batch so these paths are exercised.

Block id format: `<sha256[:8]>:p<page>:l<line>` or `<sha256[:8]>:p<page>:t<table>r<row>c<col>`.

## Run with Ollama

Place source documents in `data/raw` and run:

```bash
lab-report run --model gemma4:26b
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
