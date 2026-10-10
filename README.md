# Digital twin-enabled structural clash detection with load path-aware severity

Code, experiments and manuscript for *"A Digital Twin-Enabled Framework for Automated Structural Clash Detection and Load Path-Aware Severity Classification in BIM Using Python and Revit API"*.

**Authors:** Maleeha Waseem (corresponding, maleehawaseem30@gmail.com), Muhammad Arham, Muhammed Ahmed

**Status:** manuscript in preparation for *Automation in Construction*; not yet peer-reviewed. The severity classes have **not yet been validated against expert judgement** (see [Expert validation kit](#expert-validation-kit)).

Clash detection reports thousands of interferences but cannot tell which ones matter structurally. This framework detects structural–MEP clashes in federated Revit models on exact meshes, builds a gravity load-path graph from the model, and grades each clash by combining a code-informed local capacity-loss index with the load that depends on the member. Revit change events update the analysis incrementally, and the results are written back into Revit.

## Results at a glance

Two Revit 2027 sample buildings: Snowdon Towers (steel and joist frame with concrete cores; development case) and Golden Nugget (concrete and timber hybrid; held-out case).

| | Snowdon Towers | Golden Nugget |
|---|---:|---:|
| Structural members / MEP elements | 1,185 / 9,129 | 637 / 5,297 |
| Hard clashes | 687 | 338 |
| Detection vs Revit's `ElementIntersectsSolidFilter` (precision / recall / F1) | 0.989 / 0.999 / 0.994 | 0.962 / 0.994 / 0.978 |
| Detection time, framework / Revit filter (s) | 17 / 544 | 46 / 32 |
| Critical + Major, proposed method | 12 (1.7 %) | 15 (4.4 %) |
| Critical + Major, geometry-only triage | 387 (56.3 %) | 111 (32.8 %) |
| Twin update, median MEP / structural change | 62 ms / 5.6 s | 37 ms / 2.5 s |
| Incremental state identical to full recomputation | 6 / 6 checkpoints | 6 / 6 checkpoints |

The method was developed on Snowdon Towers and frozen before Golden Nugget was analysed. The held-out case exposed two rules that assumed a beam-and-slab structural system, and they were revised and applied to both models. The frozen-method results are kept in `results/BIM_Projekt_Golden_Nugget-Architektur_und_Ingenieurbau/frozen/`, and the paper reports both (Section 5.6, Table 6).

## What it does

1. **Revit side** (`revit/DTClash.extension`, pyRevit, IronPython 2.7, Revit 2027): exports structural and MEP elements of a host model and its links. The export includes meshes in host coordinates, attributes, Revit joins, and Revit's own `ElementIntersectsSolidFilter` pairs as a reference. A `doc-changed` hook streams deltas, and *Show Severity* writes results back as view overrides and `DirectShape` markers.
2. **Analysis service** (`src/dtclash`, CPython 3.11):
   - `clash.py`: R-tree broad phase; FCL narrow phase with a deterministic containment test; exact Manifold Booleans, applied component-wise to multi-solid families (convex-hull stand-ins for open components); clash localisation in member frames.
   - `loadpath.py`: gravity load-path graph built from contacts, Revit joins and member-end proximity, with orientation rules (braces never carry gravity load); tributary-area load propagation with exact equilibrium; dominator-based orphaned load; load-path criticality index (LPCI).
   - `severity.py`: demand-weighted capacity loss η per member type (beams, open-web joists, columns, walls, slabs per ACI 318-19, foundations) and consequence in bay-equivalents, combined in a risk matrix; geometry-only and category-rule baselines.
   - `twin.py`: fingerprints, incremental clash, load-path and severity updates, and SQLite versioning.

## Repository layout

```
revit/DTClash.extension/   pyRevit extension: exporter, change hook, ribbon buttons
revit/batch/               headless scripts for `pyrevit run` (model export, twin scenarios)
src/dtclash/               analysis package (clash, load path, severity, twin)
tests/                     synthetic cases with known answers + twin equivalence tests
experiments/               experiment, figure and survey scripts
results/<model>/           result tables of the paper (clashes, members, detection, sensitivity, twin)
data/processed/            derived tables (data/raw/ exports are not versioned)
paper/                     manuscript (.md source -> .docx/.pdf), figures, tables, references, build tools
survey/                    blinded expert rating kit
```

## Requirements

- Windows, Autodesk Revit 2027 and pyRevit 6.5.5 (only for exporting models and for the live twin).
- Python 3.11 (`requirements.txt`).
- To rebuild the manuscript: pandoc 3.x. Microsoft Word is needed for the PDF export only.

The result tables are included, so the figures, tables and manuscript can be rebuilt without Revit.

## Reproduce

Set up and run the tests:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
```

Export the two models from Revit 2027. Each host model is opened detached and read-only, its links are exported with it, and it is closed without saving:

```bash
pyrevit run revit\batch\export_model.py "C:\Program Files\Autodesk\Revit 2027\Samples\Snowdon Towers Sample Structural.rvt" --revit=2027 --purge
pyrevit run revit\batch\export_model.py "C:\Program Files\Autodesk\Revit 2027\Samples\BIM_Projekt_Golden_Nugget-Architektur_und_Ingenieurbau.rvt" --revit=2027 --purge
```

An interrupted export resumes automatically when the command is run again. Then run the experiments for each model (outputs go to `results/<model>/`; `scalability.py` was run on Snowdon Towers only):

```bash
.venv\Scripts\python experiments\run_case.py data\raw\Snowdon_Towers_Sample_Structural
.venv\Scripts\python experiments\sensitivity.py data\raw\Snowdon_Towers_Sample_Structural
.venv\Scripts\python experiments\twin_bench.py data\raw\Snowdon_Towers_Sample_Structural
.venv\Scripts\python experiments\scalability.py data\raw\Snowdon_Towers_Sample_Structural
```

Repeat the first three with `data\raw\BIM_Projekt_Golden_Nugget-Architektur_und_Ingenieurbau`. Then make the figures and build the manuscript (tables are regenerated from `results/`):

```bash
.venv\Scripts\python experiments\figures.py
.venv\Scripts\python paper\tools\build_docx.py --pdf
.venv\Scripts\python paper\tools\check_limits.py
```

Run the live twin while working in Revit (enable sync with the *Twin Sync* button):

```bash
.venv\Scripts\python experiments\twin_service.py data\raw\<model>
```

## Expert validation kit

`experiments/make_survey.py` builds `survey/Severity_Rating_Form.xlsx`: 48 blinded clash snapshots with facts and rating dropdowns. Raters never see any method's classification. Return completed forms to `survey/returned/` and run `experiments/analyse_survey.py survey/returned/*.xlsx` for Krippendorff's α, the consensus, and each method's agreement with it. See [survey/README.md](survey/README.md).

> **Note for raters:** please do not browse this repository before submitting your ratings. `survey/answer_key.csv` contains the methods' classifications.

## Use of generative AI

Software development, experiment execution and manuscript drafting were assisted by Claude Code with the Claude Opus 5.5 model (Anthropic), under the authors' direction. Results were verified independently of the tool: synthetic test cases with known answers, agreement with Revit's own intersection filter, exact load equilibrium, and identity of incremental and full recomputation. Every reference in the paper was checked against its DOI record. Details are in Section 4.1 and the declarations of the manuscript.

## Citation and licence

A citation will be added once the paper is published. No licence has been chosen yet, so all rights are reserved by the authors until one is added.

## Notes

- pyRevit 6.5.5's CLI does not recognise the pre-release build stamps of the Revit 2027 sample files (`20251213_1515`, `20260125_1515`, `20260219_1515`). Add them as Revit 2027 to the user-level `%APPDATA%\pyRevit\Cache\pyrevit-hosts.json`.
- `data/raw/` is not versioned. It is regenerated by the export script from Autodesk's sample models, which ship with Revit 2027 and are not redistributed here.
