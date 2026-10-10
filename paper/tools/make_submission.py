"""Assemble the Automation in Construction submission pack.

    .venv\\Scripts\\python paper\\tools\\make_submission.py

Rebuilds the manuscript, then writes paper/submission/AiC_pack/ (and a zip of it):
    Manuscript.docx, Highlights.docx       editable Word files
    Figure_1.pdf ... Figure_N.pdf          vector artwork, numbered in order of appearance
    Cover_letter.docx                      from paper/submission/cover_letter.md (if present)
    Submission_checklist.docx / .md        from paper/submission/Submission_checklist.md (if present)
paper/submission/ is not versioned: the cover letter and checklist are private correspondence.
Chart PDFs come from experiments/figures.py; Fig. 1 is converted from its SVG source with rsvg-convert.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parents[1]
SUB = PAPER / "submission"
PACK = SUB / "AiC_pack"
PANDOC = shutil.which("pandoc") or str(Path.home() / "AppData/Local/Pandoc/pandoc.exe")


def figure_order():
    """Figure stems in order of first appearance in the manuscript."""
    seen = []
    for stem in re.findall(r"figures/(fig\d+_[A-Za-z0-9_]+)\.png", (PAPER / "manuscript.md").read_text(encoding="utf-8")):
        if stem not in seen:
            seen.append(stem)
    return seen


def vector_pdf(stem):
    pdf = PAPER / "figures" / f"{stem}.pdf"
    svg = PAPER / "figures" / "src" / f"{stem}.svg"
    if svg.exists() and shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-f", "pdf", "-o", str(pdf), str(svg)], check=True)
    if not pdf.exists():
        sys.exit(f"missing vector artwork {pdf}: run experiments/figures.py (charts) or provide {svg.name}")
    return pdf


def checklist_text():
    src = (SUB / "Submission_checklist.md").read_text(encoding="utf-8")
    abstract = (PAPER / "tables" / "abstract.md").read_text(encoding="utf-8").strip()
    m = re.search(r"^\*\*Data availability\.\*\* (.+)$", (PAPER / "manuscript.md").read_text(encoding="utf-8"), re.M)
    return src.replace("ABSTRACT_PLACEHOLDER", abstract).replace("DATA_PLACEHOLDER", m.group(1) if m else "")


def main():
    subprocess.run([sys.executable, str(PAPER / "tools" / "build_docx.py")], check=True)
    if PACK.exists():
        shutil.rmtree(PACK)
    PACK.mkdir(parents=True)
    shutil.copy2(PAPER / "manuscript.docx", PACK / "Manuscript.docx")
    shutil.copy2(PAPER / "highlights.docx", PACK / "Highlights.docx")
    for i, stem in enumerate(figure_order(), 1):
        shutil.copy2(vector_pdf(stem), PACK / f"Figure_{i}.pdf")
    if (SUB / "cover_letter.md").exists():
        subprocess.run([PANDOC, str(SUB / "cover_letter.md"), "-o", str(PACK / "Cover_letter.docx")], check=True)
    if (SUB / "Submission_checklist.md").exists():
        md = PACK / "Submission_checklist.md"
        md.write_text(checklist_text(), encoding="utf-8")
        subprocess.run([PANDOC, str(md), "-o", str(PACK / "Submission_checklist.docx")], check=True)
    zip_path = shutil.make_archive(str(SUB / "AiC_submission_pack"), "zip", PACK)
    for f in sorted(PACK.iterdir()):
        print(f"  {f.name:28s} {f.stat().st_size / 1024:8.0f} KB")
    print("->", zip_path)


if __name__ == "__main__":
    main()
