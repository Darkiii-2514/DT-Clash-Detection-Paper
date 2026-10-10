Table: Table 4. Clash detection compared with Revit's ElementIntersectsSolidFilter. Physical clashes = hard + touch; TP / FP / FN are pairs agreed / found only by the framework / found only by Revit. {#tbl:detection}

| Quantity | Snowdon Towers | Golden Nugget |
|--------------------------------------|--------------:|--------------:|
| Candidate pairs (broad phase) | 2,040 | 3,724 |
| Clashes: hard / touch / clearance | 687 / 17 / 592 | 338 / 31 / 715 |
| Revit reference pairs | 697 | 357 |
| TP / FP / FN | 696 / 8 / 1 | 355 / 14 / 2 |
| Precision | 0.989 | 0.962 |
| Recall | 0.999 | 0.994 |
| F1 | 0.994 | 0.978 |
| Time, framework broad + narrow phase (s) | 17 | 46 |
| Time, Revit reference filter (s) | 544 | 32 |
