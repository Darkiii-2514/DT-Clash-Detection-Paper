Table: Table 4. Clash detection compared with Revit's ElementIntersectsSolidFilter. Physical clashes = hard + touch; TP/FP/FN are pairs agreed / found only by the framework / found only by Revit; times in seconds (framework: broad + narrow phase; Revit: reference filter). {#tbl:detection}

| Model | Candidates | Hard | Touch | Clearance | Revit pairs | TP / FP / FN | Precision | Recall | F1 | Time, framework (s) | Time, Revit (s) |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| Snowdon Towers | 2,040 | 687 | 17 | 592 | 697 | 696 / 8 / 1 | 0.989 | 0.999 | 0.994 | 9.8 | 544 |
