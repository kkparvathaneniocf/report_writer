from __future__ import annotations

from pathlib import Path

import pandas as pd

from lab_report.ingestion.readers import sha256
from lab_report.models import AgentOutput, Evidence, ExtractedField

COLUMNS = {
    "Wf": "wf_percent",
    "Vf": "vf_percent",
    "Density": "density_g_cm3",
    "Porosity": "porosity_percent",
}


def calculate_fiber_content(csv_path: Path) -> tuple[AgentOutput, list[Evidence], dict]:
    """Expected CSV headings: Specimen, Wf, Vf, Density, Porosity.

    Comma decimals supported in quoted fields. Other CSV formats need a deliberate mapping.
    """
    df = pd.read_csv(csv_path, sep=None, engine="python", dtype=str)
    if "Specimen" not in df.columns or "Wf" not in df.columns:
        raise ValueError("CSV requires 'Specimen' and 'Wf' columns")
    if df["Specimen"].isna().any() or df["Specimen"].duplicated().any():
        raise ValueError("Missing or duplicate specimen IDs")
    evidence: list[Evidence] = []
    fields: list[ExtractedField] = []
    statistics: dict = {}
    digest = sha256(csv_path)
    for column, label in COLUMNS.items():
        if column not in df.columns:
            fields.append(ExtractedField(field_name=label + "_mean", value=None, status="MISSING"))
            continue
        converted = pd.to_numeric(
            df[column].astype(str).str.replace(",", ".", regex=False), errors="coerce"
        )
        if converted.isna().any():
            raise ValueError(f"Column {column}: blank or non-numeric values; refuse calculation")
        if len(converted) < 2:
            raise ValueError("At least two specimens required for sample SD")
        ids = []
        for idx, (specimen, raw) in enumerate(zip(df["Specimen"], df[column], strict=True), 2):
            eid = f"F{column.upper()}{idx}"
            evidence.append(
                Evidence(
                    id=eid,
                    source_file=csv_path.name,
                    source_sha256=digest,
                    source_location=f"row:{idx}/column:{column}",
                    quote=f"Specimen={specimen}; {column}={raw}",
                    method="csv_cell",
                )
            )
            ids.append(eid)
        mean = float(converted.mean())
        sd = float(converted.std(ddof=1))
        statistics[label] = {
            "n": len(converted),
            "mean": mean,
            "sample_sd": sd,
            "cv_percent": sd / abs(mean) * 100 if mean else None,
            "min": float(converted.min()),
            "max": float(converted.max()),
        }
        fields.append(
            ExtractedField(
                field_name=label + "_mean", value=f"{mean:.3f}", evidence_ids=ids, status="VERIFIED"
            )
        )
    return AgentOutput(section_id="2.1.5", fields=fields), evidence, statistics
