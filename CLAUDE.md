# DT-Clash-Detection-Paper

Research paper + implementation: **"A Digital Twin-Enabled Framework for Automated Structural Clash Detection and Load Path-Aware Severity Classification in BIM Using Python and Revit API"**.

## Decisions (from the author, 2026-10-09)
- Scope: full build + paper — real implementation, real experiments, real numbers. Never invent results, labels, or citations.
- Manuscript format: Word (.docx). Target journal: *Automation in Construction* (Elsevier).
- Every reference must be verified (DOI via Crossref/OpenAlex) before it enters the manuscript.

## Layout
- `revit/DTClash.extension/` — pyRevit extension (runs inside Revit 2027): element/geometry/connectivity export, change hooks, result write-back.
- `revit/batch/` — scripts run headless via `pyrevit run <script> <model.rvt> --revit=2027`.
- `src/dtclash/` — CPython analysis package: broad/narrow-phase clash detection, load-path graph, severity classification, digital-twin sync.
- `experiments/` — reproducible experiment scripts; outputs to `results/`.
- `data/raw/` — exports from Revit (gitignored, regenerable). `data/processed/` — derived tables.
- `paper/` — manuscript (.docx), `refs.bib`, final figures.

## Environment
- Python: `.venv\Scripts\python.exe` (3.11); deps in `requirements.txt`.
- Revit 2027 (.NET 10). pyRevit CLI: `C:\Program Files\pyRevit-Master\bin\pyrevit.exe` (default engine IronPython 2.7 — keep Revit-side code 2.7-compatible unless the script starts with `#! python3`).
- Test models (read-only, never modify): `C:\Program Files\Autodesk\Revit 2027\Samples\` — Snowdon Towers (Structural / HVAC / Plumbing / Electrical) and BIM_Projekt_Golden_Nugget (Architektur_und_Ingenieurbau / Gebaeudetechnik).
