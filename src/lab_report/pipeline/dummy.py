"""Generate a fake TR folder (PDFs) with the same document types as a real test request.

Planted defects, so traceability can be exercised:
  * fabric batch differs between COA (24B1187) and infusion report (24B1178) -> CONFLICT
  * catalyst batch absent from the infusion report -> MISSING
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

TR = "TR26_C0143"
FWF_ROWS = [
    ("69,64", "50,18", "1,881", "0,46"),
    ("70,42", "51,05", "1,892", "0,59"),
    ("70,41", "50,89", "1,886", "0,86"),
    ("69,80", "50,24", "1,879", "0,73"),
    ("70,63", "51,18", "1,891", "0,81"),
]
TENSILE_ROWS = [  # thickness, width, Fmax, stress at break, modulus, linear est. strain, failure
    ("1,012", "25,03", "28,41", "1121", "45,2", "2,48", "LGM"),
    ("1,008", "24,98", "27,96", "1110", "44,8", "2,47", "LGM"),
    ("1,015", "25,01", "28,90", "1138", "45,6", "2,50", "LAT"),
    ("1,010", "25,05", "27,52", "1088", "44,9", "2,42", "LGM"),
    ("1,011", "24,99", "28,33", "1121", "45,4", "2,47", "LGM"),
]


class PdfWriter:
    """Minimal PDF author: labelled lines and ruled tables, like typical lab software output."""

    def __init__(self, title: str):
        self.doc = pymupdf.open()
        self.page = self.doc.new_page()
        self.y = 60.0
        self.text(title, size=15, bold=True)
        self.y += 6

    def _room(self, height: float) -> None:
        if self.y + height > 800:
            self.page = self.doc.new_page()
            self.y = 60.0

    def text(self, value: str, size: float = 10, bold: bool = False) -> None:
        self._room(size + 6)
        font = "hebo" if bold else "helv"
        self.page.insert_text((50, self.y), value, fontsize=size, fontname=font)
        self.y += size + 6

    def kv(self, label: str, value: str) -> None:
        self.text(f"{label}: {value}")

    def gap(self, h: float = 8) -> None:
        self.y += h

    @staticmethod
    def _wrap(value: str, width: float, font: str, size: float) -> list[str]:
        lines, current = [], ""
        for word in value.split():
            trial = f"{current} {word}".strip()
            if current and pymupdf.get_text_length(trial, fontname=font, fontsize=size) > width:
                lines.append(current)
                current = word
            else:
                current = trial
        return [*lines, current]

    def table(self, headers: list[str], rows: list[tuple], widths: list[float]) -> None:
        size, leading = 8.5, 11.0
        for r_index, row in enumerate([tuple(headers), *rows]):
            font = "hebo" if r_index == 0 else "helv"
            cells = [
                self._wrap(str(v), w - 6, font, size) for v, w in zip(row, widths, strict=True)
            ]
            h = max(len(c) for c in cells) * leading + 7
            self._room(h if r_index else h + 30)
            x = 50.0
            for lines, w in zip(cells, widths, strict=True):
                self.page.draw_rect(pymupdf.Rect(x, self.y, x + w, self.y + h), width=0.6)
                for i, line in enumerate(lines):
                    pos = (x + 3, self.y + 3 + size + i * leading)
                    self.page.insert_text(pos, line, fontsize=size, fontname=font)
                x += w
            self.y += h
        self.y += 12

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(path)
        return path


def test_request(folder: Path) -> Path:
    w = PdfWriter("Test Request - Mechanical Testing Laboratory")
    w.kv("TR N°", TR)
    w.kv("Requester", "R. REGATTIERI")
    w.kv("Request date", "2026-06-02")
    w.kv("Product name", "UD-1200 WS4000 epoxy laminate")
    w.kv("Laminate N°", "260612VB-A")
    w.gap()
    w.text("Product description", bold=True)
    for line in (
        "Unidirectional glass fabric 1200 g/m² based on WS4000 roving, vacuum infused",
        "with epoxy resin EP-200. Intended for wind blade spar caps. Panels were",
        "produced by the OCV CI Wind Prototyping team.",
    ):
        w.text(line)
    w.gap()
    w.text("Requested tests", bold=True)
    w.table(
        ["Test", "Direction (°)", "Standard", "Specimens"],
        [("Fiber content", "-", "ISO 1172", "5"), ("Tensile", "0", "ISO 527-4", "5")],
        [150, 90, 120, 80],
    )
    w.text("Testing standards", bold=True)
    w.table(
        ["Number", "Title", "DNV Certified"],
        [
            ("ISO 1172", "Textile-glass-reinforced plastics - Calcination methods", "Yes"),
            ("ASTM D2734", "Void content of reinforced plastics", "No"),
            ("ISO 527-4", "Plastics - Tensile properties - Part 4: composites", "Yes"),
        ],
        [90, 300, 90],
    )
    w.text("Internal operating procedures", bold=True)
    w.table(
        ["Number", "Title"],
        [
            ("MM.LEM.015", "Traction ISO 527-4 indice G"),
            ("MM.LEM.022", "Taux de verre ISO 1172 indice F"),
            ("MM.LEM.084", "Mesure de la densité, porosité, FWF, FVF indice C"),
        ],
        [100, 380],
    )
    return w.save(folder / f"{TR}_test_request.pdf")


def fwf_file(folder: Path) -> Path:
    w = PdfWriter("Fiber content - ISO 1172 / ASTM D2734-B - Test file")
    w.kv("TR N°", TR)
    w.kv("Technician", "P. BERTELONE")
    w.kv("Test date", "2026-06-18")
    w.kv("Resin density", "1,15 g/cm3")
    w.kv("Fiber density", "2,60 g/cm3")
    w.kv("Specimen size", "20 x 20 mm")
    w.gap()
    w.text("Equipment", bold=True)
    w.table(
        ["N°", "Equipment", "Type / description", "Calibration date"],
        [
            ("992", "Weighing scale", "Accuracy of 0,01 g", "02/12/2026"),
            ("578", "Muffle furnace, Heraeus M110", "625 °C", "15/01/2027"),
        ],
        [50, 170, 150, 100],
    )
    w.text("Results", bold=True)
    w.table(
        ["Specimen", "Wf [%]", "Vf [%]", "Density [g/cm3]", "Porosity [%]"],
        [(f"{TR}_01_{i}", *row) for i, row in enumerate(FWF_ROWS, 1)],
        [130, 70, 70, 100, 80],
    )
    return w.save(folder / f"{TR}_FWF_ISO1172.pdf")


def tensile_report(folder: Path) -> Path:
    w = PdfWriter("testXpert - Test report - Tensile")
    w.kv("TR N°", TR)
    w.kv("Test", "Tensile 0°")
    w.kv("Standard", "ISO 527-4 type 3")
    w.kv("Operator", "M. GARNIER")
    w.kv("Prestress", "5 MPa")
    w.kv("Test speed", "2 mm/min")
    w.gap()
    w.text("Test equipment and fixture", bold=True)
    w.table(
        ["N°", "Equipment", "Type / description"],
        [
            ("1043", "Universal testing machine", "Zwick Z250, 250 kN load cell"),
            ("1102", "Extensometer", "Clip-on, gauge length 50 mm"),
            ("1187", "Hydraulic grips", "Wedge grips 250 kN"),
        ],
        [50, 180, 250],
    )
    w.text("Results", bold=True)
    w.table(
        [
            "Specimen",
            "Thickness [mm]",
            "Width [mm]",
            "Fmax [kN]",
            "Stress at break [MPa]",
            "Modulus [GPa]",
            "Lin. est. strain [%]",
            "Failure",
        ],
        [(f"{TR}_02_{i}", *row) for i, row in enumerate(TENSILE_ROWS, 1)],
        [95, 55, 50, 50, 65, 55, 60, 45],
    )
    return w.save(folder / f"{TR}_tensile_0deg_report.pdf")


def coa(folder: Path) -> Path:
    w = PdfWriter("CERTIFICATE OF ANALYSIS")
    w.kv("Supplier", "Fabrics Plant A (dummy)")
    w.kv("Material description", "UD glass fabric 1200 g/m²")
    w.kv("Material code", "UD1200-WS4000")
    w.kv("Production date", "2026-04-14")
    w.kv("Batch N°", "24B1187")
    w.kv("Roll N°", "R-0457")
    w.kv("Mfg plant", "Plant A")
    w.gap()
    w.table(
        ["Property", "Unit", "Specification", "Result"],
        [
            ("Areal weight", "g/m²", "1200 ± 5 %", "1207"),
            ("Moisture", "%", "< 0,1", "0,04"),
            ("Size content (LOI)", "%", "0,45 - 0,75", "0,58"),
        ],
        [150, 60, 130, 100],
    )
    return w.save(folder / "Fabric_COA_24B1187.pdf")


def infusion_report(folder: Path) -> Path:
    w = PdfWriter("Infusion report")
    w.kv("Laminate N°", "260612VB-A")
    w.kv("Fabric batch", "24B1178")  # planted conflict with the COA
    w.kv("Resin", "Epoxy resin EP-200")
    w.kv("Resin supplier", "ResinCo (dummy)")
    w.kv("Resin batch", "RB-55102")
    w.kv("Catalyst", "Hardener EH-210")
    w.kv("Catalyst supplier", "ResinCo (dummy)")
    # Catalyst batch intentionally not recorded.
    w.kv("Depression", "-0,95 bar")
    w.kv("Infusion temperature", "25 °C")
    w.kv("Curing temperature", "70 °C")
    w.kv("Post-curing", "8 h / 80 °C")
    w.kv("SOP N°", "TF-SOP-012")
    return w.save(folder / "Infusion_report_260612VB-A.pdf")


def make_dummy_tr_folder(folder: Path) -> list[Path]:
    return [f(folder) for f in (test_request, fwf_file, tensile_report, coa, infusion_report)]
