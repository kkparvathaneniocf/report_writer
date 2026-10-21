from pathlib import Path
import pytest
from lab_report.agents.fiber_content import calculate_fiber_content
from lab_report.validation.evidence import validate_output
from lab_report.models import AgentOutput, ExtractedField


def test_known_fiber_values():
    path = Path(__file__).parents[1] / "examples" / "TR26_C0143_fiber.csv"
    output, evidence, statistics = calculate_fiber_content(path)
    assert abs(statistics["wf_percent"]["mean"] - 70.18) < 0.01
    assert statistics["wf_percent"]["n"] == 5
    assert all(f.status == "VERIFIED" for f in output.fields)
    assert all(e.source_sha256 for e in evidence)


def test_missing_evidence_flagged():
    result = AgentOutput(section_id="a", fields=[ExtractedField(field_name="claim", value="abc", evidence_ids=["FAKE"])])
    assert validate_output(result, [], []).fields[0].status == "NEEDS_REVIEW"


def test_invalid_csv_rejected(tmp_path):
    path = tmp_path / "fiber.csv"
    path.write_text("Specimen,Wf\na,20\nb,bad\n")
    with pytest.raises(ValueError, match="non-numeric"):
        calculate_fiber_content(path)
