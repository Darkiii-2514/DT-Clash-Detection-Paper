"""Assemble a journal submission pack: --journal aic (Automation in Construction, the default) or
--journal asce (Journal of Computing in Civil Engineering: ASCE manuscript, no highlights, Video_S1).

    .venv\\Scripts\\python paper\\tools\\make_submission.py [--journal aic|asce]

Rebuilds the manuscript, then writes paper/submission/AiC_pack/ (and a zip of it):
    Manuscript.docx, Highlights.docx       editable Word files
    Figure_1.pdf ... Figure_N.pdf          vector artwork, numbered in order of appearance
    Supplementary_Video_N.mp4              from paper/supplementary/ (experiments/make_twin_video.py)
    Cover_letter.docx / .pdf               from paper/submission/cover_letter.md (if present; PDF via Word)
    Submission_checklist.docx              from paper/submission/Submission_checklist.md (if present)
paper/submission/ is not versioned: the cover letter and checklist are private correspondence.
Chart PDFs come from experiments/figures.py; Fig. 1 is converted from its SVG source with rsvg-convert.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAPER / "tools"))
from build_docx import export_pdf  # noqa: E402
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", choices=("aic", "asce"), default="aic",
                    help="aic: Automation in Construction pack; asce: Journal of Computing in Civil Engineering pack")
    asce = ap.parse_args().journal == "asce"
    pack = SUB / ("JCCE_pack" if asce else "AiC_pack")
    subprocess.run([sys.executable, str(PAPER / "tools" / "build_docx.py")] + (["--journal", "asce"] if asce else []),
                   check=True)
    if pack.exists():
        shutil.rmtree(pack)
    pack.mkdir(parents=True)
    shutil.copy2(PAPER / ("manuscript_asce.docx" if asce else "manuscript.docx"), pack / "Manuscript.docx")
    if not asce:                                       # ASCE journals do not use highlights
        shutil.copy2(PAPER / "highlights.docx", pack / "Highlights.docx")
    for i, stem in enumerate(figure_order(), 1):
        shutil.copy2(vector_pdf(stem), pack / f"Figure_{i}.pdf")
    # since 5 Jan 2026 ASCE no longer hosts supplemental files: the ASCE manuscript links to the video instead
    for i, v in enumerate(sorted((PAPER / "supplementary").glob("Video_*.mp4")), 1):
        if not asce:
            shutil.copy2(v, pack / f"Supplementary_Video_{i}.mp4")
    letter_src = SUB / ("cover_letter_jcce.md" if asce else "cover_letter.md")
    if letter_src.exists():
        letter = pack / "Cover_letter.docx"
        subprocess.run([PANDOC, str(letter_src), "-o", str(letter)], check=True)
        try:
            export_pdf(letter, letter.with_suffix(".pdf"))      # Word, if installed
        except Exception as ex:
            print("cover letter PDF skipped:", ex)
    if not asce and (SUB / "Submission_checklist.md").exists():
        md = SUB / "_checklist_filled.md"
        md.write_text(checklist_text(), encoding="utf-8")
        subprocess.run([PANDOC, str(md), "-o", str(pack / "Submission_checklist.docx")], check=True)
        md.unlink()
    zip_path = shutil.make_archive(str(SUB / ("JCCE_submission_pack" if asce else "AiC_submission_pack")), "zip", pack)
    for f in sorted(pack.iterdir()):
        print(f"  {f.name:28s} {f.stat().st_size / 1024:8.0f} KB")
    print("->", zip_path)


if __name__ == "__main__":
    main()
