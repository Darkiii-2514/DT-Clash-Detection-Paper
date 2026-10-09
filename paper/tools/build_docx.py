"""Build the Word manuscript (and highlights) from paper/manuscript.md.

    .venv\\Scripts\\python paper\\tools\\build_docx.py [--pdf]

1. reference.docx: Times New Roman 12 pt, double spacing, A4, 2.5 cm margins (review format)
2. pandoc: numbered sections, citeproc with the Elsevier numeric style (Automation in
   Construction), TeX math -> native Word equations, figures from paper/figures
3. python-docx post-processing: continuous line numbers (journal requirement for review),
   centred page numbers, readable table borders
4. --pdf: export a PDF through Microsoft Word for visual checking
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

PAPER = Path(__file__).resolve().parents[1]
PANDOC = shutil.which("pandoc") or str(Path.home() / "AppData/Local/Pandoc/pandoc.exe")
REF = PAPER / "style" / "reference.docx"


def _force_font(style, name="Times New Roman"):
    """Set explicit fonts and drop theme-font attributes (they override explicit ones)."""
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in list(rfonts.attrib):
        if attr.endswith("Theme"):
            del rfonts.attrib[attr]
    for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(k), name)


def make_reference():
    # write straight to the file: piping binary through stdout on Windows corrupts the zip
    subprocess.run([PANDOC, "-o", str(REF), "--print-default-data-file", "reference.docx"], check=True)
    d = Document(REF)
    st = d.styles
    for name in ("Normal", "Body Text", "First Paragraph", "Compact", "Abstract", "Bibliography", "Subtitle", "Author"):
        if name in [s.name for s in st]:
            s = st[name]
            s.font.name = "Times New Roman"
            s.font.size = Pt(12)
            s.font.color.rgb = RGBColor(0, 0, 0)
            _force_font(s)
            pf = s.paragraph_format
            pf.line_spacing = 2.0
            pf.space_after = Pt(0)
            pf.space_before = Pt(0)
    for lvl, size in ((1, 12), (2, 12), (3, 12)):
        s = st[f"Heading {lvl}"]
        s.font.name = "Times New Roman"
        _force_font(s)
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.italic = lvl == 3
        s.font.color.rgb = RGBColor(0, 0, 0)
        s.paragraph_format.space_before = Pt(12)
        s.paragraph_format.space_after = Pt(6)
        s.paragraph_format.line_spacing = 2.0
    for name in ("Title", "Abstract Title"):
        if name not in [x.name for x in st]:
            continue
        s = st[name]
        s.font.name = "Times New Roman"
        _force_font(s)
        s.font.size = Pt(16)
        s.font.bold = True
        s.font.color.rgb = RGBColor(0, 0, 0)
    for name in ("Image Caption", "Table Caption", "Caption"):
        if name in [s.name for s in st]:
            s = st[name]
            s.font.name = "Times New Roman"
            _force_font(s)
            s.font.size = Pt(10)
            s.font.italic = False
            s.font.color.rgb = RGBColor(0, 0, 0)
            s.paragraph_format.line_spacing = 1.15
            s.paragraph_format.space_after = Pt(10)
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(2.5))
    d.save(REF)


def add_line_numbers_and_page_numbers(path: Path):
    d = Document(path)
    for sec in d.sections:
        sp = sec._sectPr
        ln = sp.find(qn("w:lnNumType"))
        if ln is None:
            ln = OxmlElement("w:lnNumType")
            sp.append(ln)
        ln.set(qn("w:countBy"), "1")
        ln.set(qn("w:restart"), "continuous")
        ln.set(qn("w:distance"), "360")
        p = sec.footer.paragraphs[0] if sec.footer.paragraphs else sec.footer.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
            if tag:
                f = OxmlElement("w:fldChar")
                f.set(qn("w:fldCharType"), tag)
                run._r.append(f)
            else:
                t = OxmlElement("w:instrText")
                t.set(qn("xml:space"), "preserve")
                t.text = text
                run._r.append(t)
    # tables: thin horizontal rules (booktabs-like), compact single spacing
    for tbl in d.tables:
        tblPr = tbl._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge, val in (("top", "single"), ("bottom", "single"), ("insideH", "single"),
                          ("left", "nil"), ("right", "nil"), ("insideV", "nil")):
            b = OxmlElement(f"w:{edge}")
            b.set(qn("w:val"), val)
            b.set(qn("w:sz"), "4")
            b.set(qn("w:color"), "808080")
            borders.append(b)
        tblPr.append(borders)
        for row in tbl.rows:
            for cell in row.cells:
                for par in cell.paragraphs:
                    par.paragraph_format.line_spacing = 1.0
                    for r in par.runs:
                        r.font.size = Pt(10)
    d.save(path)


def export_pdf(docx: Path, pdf: Path):
    ps = (f"$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
          f"$d = $w.Documents.Open('{docx}', $false, $true); "
          f"$d.ExportAsFixedFormat('{pdf}', 17); $d.Close($false); $w.Quit()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--rebuild-reference", action="store_true")
    a = ap.parse_args()
    if a.rebuild_reference or not REF.exists():
        make_reference()
    out = PAPER / "manuscript.docx"
    # insert generated tables / blocks at their <!--NAME--> placeholders
    src = (PAPER / "manuscript.md").read_text(encoding="utf-8")
    for f in sorted((PAPER / "tables").glob("*.md")):
        src = src.replace(f"<!--{f.stem.upper()}-->", f.read_text(encoding="utf-8"))
    missing = [m for m in ("TABLE3", "TABLE4", "TABLE5") if f"<!--{m}-->" in src]
    if missing:
        print("warning: placeholders not filled:", missing)
    (PAPER / "_build.md").write_text(src, encoding="utf-8")
    cmd = [PANDOC, "_build.md", "--citeproc", "--number-sections", "--reference-doc", str(REF),
           "--resource-path", str(PAPER), "-o", str(out)]
    r = subprocess.run(cmd, cwd=PAPER, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    if r.stderr.strip():
        print(r.stderr.strip())
    add_line_numbers_and_page_numbers(out)
    hl = PAPER / "highlights.md"
    if hl.exists():
        subprocess.run([PANDOC, str(hl), "--reference-doc", str(REF), "-o", str(PAPER / "highlights.docx")],
                       check=True)
    print("->", out)
    if a.pdf:
        export_pdf(out, out.with_suffix(".pdf"))
        print("->", out.with_suffix(".pdf"))


if __name__ == "__main__":
    main()
