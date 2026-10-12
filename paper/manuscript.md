---
title: "A Digital Twin-Enabled Framework for Automated Structural Clash Detection and Load Path-Aware Severity Classification in BIM Using Python and Revit API"
author:
  - 'Muhammad Ahmed^a,\*^, Maleeha Waseem^a^, Muhammad Arham^a^'
  - '^a^ Department of Civil Engineering, Ghulam Ishaq Khan Institute of Engineering Sciences and Technology, Topi 23640, Swabi, Khyber Pakhtunkhwa, Pakistan'
  - '^\*^ Corresponding author. E-mail addresses: muhammed.ahmed0999@gmail.com (Muhammad Ahmed), maleehawaseem30@gmail.com (Maleeha Waseem), muhammadarham6333@gmail.com (Muhammad Arham).'
bibliography: refs.bib
csl: style/elsevier-with-titles.csl
link-citations: true
---

# Abstract {.unnumbered}

<!--ABSTRACT-->

**Keywords:** Building information modelling; Clash detection; Digital twin; Load path; Severity classification; Revit API; Structural robustness

# Introduction

Clash detection is one of the most widely used building information modelling (BIM) workflows: federated discipline models are checked geometrically, and every interference, for example between a duct and a beam, is reported for resolution before construction. Clashes that surface on site cause rework, delay and cost [@chahrour2020], and coordination problems remain frequent because disciplines model in isolation [@akponeware2017]. Commercial clash engines, however, report thousands of interferences per building, many of them irrelevant or duplicates of one issue [@hu2019; @lin2019], so coordinators spend much of their time triaging reports [@borkowski2026; @koo2026].

Research has therefore concentrated on *relevance*: learning from past coordination decisions which clashes a coordinator would discard [@hu2019; @lin2019; @ailem2026; @koo2026], or ranking clashes with expert-weighted attributes of the elements involved [@bitaraf2024]. These approaches reproduce coordinator judgement but do not reason about what a clash does to the structure. A 100 mm pipe through the web of a girder near its support, or through a slab within the punching-shear perimeter of a column, can be far more serious than a larger duct that grazes a non-load-bearing element. Geometrically identical clashes can also differ in consequence, depending on how much of the building depends on the cut member, a property of the structure's *load path* that no clash report represents. At the same time, coordination is moving toward *digital twins*, virtual representations that are updated continuously as the design changes [@boje2020; @sacks2020], in which clash checking should be an incremental service rather than a periodic batch job.

This paper presents a framework that (i) extracts structural and MEP elements, their geometry and their connectivity from Autodesk Revit through its application programming interface (API) using Python; (ii) detects clashes on exact meshes; (iii) builds a gravity load-path graph that gives, for every member, the load that depends on it and the load that has no alternative path; (iv) grades each clash by combining a code-informed local capacity loss with this load-path consequence; and (v) keeps the analysis synchronised with Revit as a digital twin that writes its results back. The contributions are:

1. A gravity load-path graph built automatically from BIM geometry and Revit connectivity, with exact equilibrium and a dominator-tree measure of *orphaned load*, a graph analogue of the alternate-load-path concept of progressive-collapse design [@ufc2016; @starossek2010].
2. A two-axis severity model that combines a member-specific, code-informed capacity loss index [@aci2019; @darwin1990] with a load-path consequence expressed in bay-equivalents.
3. Incremental digital-twin updates of clashes, load path and severity that are identical to a full recomputation, closed through a Revit change hook and a write-back command.
4. An open evaluation on two federated Revit models of different structural systems, including a held-out test that exposed, and led to correcting, two rules that silently assumed a particular structural system.

# Related work

## Clash detection and relevance filtering

Clash engines compare element geometry pairwise after a spatial pre-selection, for example with an R-tree [@guttman1984], and libraries such as FCL provide collision and distance queries on triangle meshes [@pan2012]; the bottleneck is interpretation rather than computation. Hu and Castro-Lacouture classified clashes as relevant or irrelevant from attributes of the clashing components [@hu2019] and later exploited dependencies between components and between clashes [@hu2019b]. Lin and Huang combined expert rules with supervised learning [@lin2019]. More recent work packages relevance filtering as a BIM plug-in [@ailem2026], aligns risk and relevance analysis with coordination practice [@koo2026], proposes AI-based triage that groups recurring clashes [@borkowski2026], and prioritises structure–MEP hard clashes with expert-weighted criteria [@bitaraf2024]. In all of these, severity or relevance is inferred from element attributes or learned from past decisions, and the structural role of the member is at most a categorical feature. None of them, to the authors' knowledge, evaluates how much capacity a penetration removes where it occurs, or how much of the building depends on the member.

## Structural knowledge, load paths and digital twins

Automated rule checking executes code requirements on BIM data [@eastman2009; @solihin2015]. Design codes contain explicit provisions for penetrations: ACI 318 limits slab openings by their position relative to column and middle strips, reduces the punching-shear perimeter for openings near columns and limits embedded conduits [@aci2019]; steel design guidance limits web openings by depth and location [@darwin1990]; and tests show that the effect of web openings in concrete beams depends on their size and position [@ahmed2012]. These provisions have not been used to grade clashes automatically. Robustness, the insensitivity of a structure to local damage, depends on alternative load paths [@starossek2010], which the alternate-path method of progressive-collapse design checks by notional member removal [@ufc2016]. In graph terms, a node *d* dominates node *n* if every path from the root to *n* passes through *d* [@lengauer1979], which answers directly whose failure leaves a load with no other path to the ground. Finally, a digital twin couples a virtual model and its counterpart automatically in both directions [@kritzinger2018]. Construction digital twins aim at closed control loops between design and execution [@boje2020; @sacks2020], but design coordination is still run on exported snapshots whose results are not fed back into the authoring model.

## Research gap

What is missing is a method that grades structural clashes by *mechanics* (the capacity a penetration removes where it occurs) and by *consequence* (the load that depends on the member), computed automatically from the authoring model and kept up to date as the model changes. This study asks four research questions:

- **RQ1** Can structural clashes be detected from Revit API data with accuracy comparable to Revit's own geometric engine, and fast enough for interactive use?
- **RQ2** Can a gravity load-path graph that satisfies equilibrium be constructed automatically from BIM geometry and connectivity?
- **RQ3** How does load-path-aware severity classification differ from geometry-only and category-based triage, and how sensitive is it to its judgement-based parameters?
- **RQ4** Can the analysis be maintained incrementally as a digital twin, with results identical to full recomputation, at interactive latency?

# Framework

## Overview

Fig. 1 shows the architecture. A pyRevit extension inside Revit extracts structural and MEP elements from the host model and its links. A Python service detects clashes, builds the load-path graph and classifies severity, and a digital-twin layer keeps it synchronised with Revit through change events and writes results back. The two sides exchange JSON files through an inbox and an outbox, so the analysis runs in standard CPython, independent of Revit's embedded interpreter.

![Fig. 1. Architecture of the digital twin-enabled framework. Revit-side components (left) run inside Revit through pyRevit; the analysis service (right) runs in CPython. The loop is closed by the document-changed hook (Revit → twin) and the write-back command (twin → Revit).](figures/fig1_architecture.png){#fig:arch width=90%}

## Data extraction through the Revit API

Structural elements are taken from the *Structural Columns*, *Structural Framing* and *Structural Foundations* categories and from floors and walls flagged as structural, by default from the host (structural) model only. MEP elements are ducts, pipes, cable trays, conduits, their fittings and accessories, mechanical equipment and sprinklers in the host and all loaded links. The fine-detail solids of each element are tessellated (`SolidUtils.TessellateSolidOrShell`), transformed into host coordinates and converted to metres, giving closed meshes that support exact Booleans. The extractor also records type, level, location curve, material, section and MEP size parameters, and two kinds of connectivity for structural members: elements joined at framing ends (`LocationCurve.ElementsAtJoin`) and geometry joins (`JoinGeometryUtils`). As an independent reference for detection accuracy, it asks Revit which MEP elements intersect each structural solid, using `ElementIntersectsSolidFilter`.

## Clash detection

A clash is a pair $(s,m)$ of a structural element $s\in\mathcal{S}$ and an MEP element $m\in\mathcal{M}$ whose meshes intersect or come closer than a clearance $c$ (25 mm). In the broad phase, inflated MEP bounding boxes are inserted into an R-tree [@guttman1984] and queried with each structural box; a vectorised brute-force test over all pairs serves as baseline and correctness check. In the narrow phase, candidates are tested with FCL collision on the meshes [@pan2012]. Because surface tests cannot see an element embedded entirely within another, a deterministic ray-parity test along three fixed directions also checks containment. Colliding or contained pairs are intersected with a robust mesh Boolean (Manifold), component by component for multi-solid families such as open-web joists; open components of detailed equipment families are replaced by their convex hulls. A pair is a *hard* clash if the intersection volume exceeds 1 cm³ and a *touch* otherwise; non-colliding pairs within $c$ are *clearance* clashes. Each structural member has a local frame $(\mathbf{u},\mathbf{v},\mathbf{w})$, with $\mathbf{u}$ along its axis and $\mathbf{w}$ vertical for horizontal members, and its length $L$, width $b$ and depth $h$ are measured from its own mesh, independent of family parameter names. The intersection solid is expressed in this frame, giving its extents $(\Delta u,\Delta v,\Delta w)$, its position in the cross-section and its normalised position along the member, $\xi\in[0,1]$.

## Gravity load-path graph

The graph has one node per structural member and a ground node $\Gamma$; an edge $a\rightarrow b$ means "$a$ is supported by $b$". Candidate support relations come from physical contact (mesh distance of at most 50 mm), Revit joins, and member-end proximity, where a beam or brace end lies within 150 mm of another member, as in centre-line analytical models. The last source is needed because steel members are often cut back at connections. Each contact is oriented, or discarded, by the rules in Table 1, which encode the hierarchy slab → beam → girder → column/wall → foundation → ground. For a beam and a column or wall, the decisive question is whether the vertical member continues below the beam (the beam frames into it) or starts within or above the beam (it stands on the beam), which is insensitive to timber tenons sinking into sill beams. Braces belong to the lateral system and never act as supports, and columns and walls separated only by a slab are stacked directly. Foundations connect to $\Gamma$, cycles are broken by removing the edge that most violates the hierarchy, and members without a path to $\Gamma$ are reported as *unsupported*.

Table: Table 1. Orientation rules for a contact between members $a$ and $b$ ($z^{\mathrm{bot}}$, $z^{\mathrm{top}}$: bottom and top elevations; $t$: contact tolerance). {#tbl:rules}

| Member pair | Rule (edge = "is supported by") |
|---|---|
| slab – beam | slab → beam if $z^{\mathrm{top}}_{beam}\le z^{\mathrm{top}}_{slab}+t$, else beam → slab |
| beam – column / wall | beam → column/wall if the vertical member continues below the beam ($z^{\mathrm{bot}}_{v}<z^{\mathrm{bot}}_{beam}-t$); column/wall → beam (transfer) if it starts within or above the beam's depth and rises above it ($z^{\mathrm{top}}_{v}>z^{\mathrm{top}}_{beam}+t$); a stub within the beam depth: beam → stub if a beam end lies within its half-width $+ t + 0.15$ m |
| brace – any | brace → member (braces never support); brace – brace: no gravity relation |
| beam – beam | secondary → primary if one beam's end lands on the other's span (not end-to-end) |
| column/wall – column/wall | upper → lower (stacking, also across a slab if the gap is ≤ 1.2 m and plans overlap ≥ 25 %) |
| column/wall – slab | slab → column/wall, unless the member stands on the slab (transfer) |
| any – foundation | member → foundation; foundation → ground $\Gamma$ |
| slab – slab, foundation – foundation | no gravity relation |

**Loads.** Each member carries its factored self-weight $q_i^{\mathrm{own}}=1.2\,\gamma\,V_i$ ($\gamma$ = 24 kN/m³ for concrete, 77 kN/m³ for steel); slabs also carry superimposed dead and live loads of 1.5 and 2.4 kPa [@asce2022] combined as $1.2D+1.6L$. Loads are propagated in topological order, $D_i=q_i^{\mathrm{own}}+\sum_{j\rightarrow i}\phi_{ji}\,D_j$, with fractions $\phi$ from tributary areas on a 0.5 m grid for slabs, tributary lengths for beams, braces and walls, and plan overlap otherwise. Load is passed only to supports that reach $\Gamma$, so the load entering the ground equals the total supported load exactly.

**Orphaned load and criticality.** In the reversed graph rooted at $\Gamma$, the immediate-dominator tree [@lengauer1979; @hagberg2008] gives, for each member $i$, the set $\mathrm{Dom}(i)$ of members whose every path to the ground passes through $i$. The orphaned load

$$E_i=\sum_{j\in \mathrm{Dom}(i)} q^{\mathrm{own}}_j \qquad (1)$$

is the load left without an alternative path if $i$ is lost, a graph analogue of the alternate-path check [@ufc2016]. $D_i$ and $E_i$ are combined into the load-path criticality index

$$\mathrm{LPCI}_i=(1-\alpha)\,g(D_i)+\alpha\,g(E_i),\qquad g(x)=\frac{\ln(1+x/D_{\mathrm{ref}})}{\ln(1+D_{\max}/D_{\mathrm{ref}})} \qquad (2)$$

where $D_{\mathrm{ref}}$ is the median load a member receives directly from a slab it supports (a typical floor bay), $D_{\max}$ is the largest load on a non-slab member and $\alpha=0.3$; the logarithm puts joists, girders and columns on one scale. Because a storey slab is often a single Revit element, a slab clash is assessed for its local panel, $D=q\,R^2$ with $R=\mathrm{clip}(2d_s,1,6)$ m, where $d_s$ is the plan distance to the nearest member beneath the slab, plus any column or wall bearing on the slab within $R$ ($R=1$ m on grade).

## Load path-aware severity classification

Severity combines the capacity removed at the clash location with the load that depends on the member there. The local impact is the demand-weighted capacity loss index

$$\eta=\max_{a}\; f_a(\xi)\,\ell_a \qquad (3)$$

where, for each action $a$ (flexure, shear, axial, punching), $\ell_a\in[0,1]$ is the fraction of sectional capacity removed by the clash region and $f_a(\xi)\in[0,1]$ is the relative demand at the clash location; for beams, $f_M=4\xi(1-\xi)$ and $f_V=|1-2\xi|$. The member-specific loss models, given in full in the released code, are:

- *Concrete beams*: a hole of height $h_o$ and width $b_h$ at offset $y_0$ from mid-depth gives $\ell_M=(b_h/b)\,[(h_o/h)^3+12(h_o/h)(y_0/h)^2]$ and $\ell_V=(b_h/b)(h_o/h)(1+0.5\,\Delta u/h)$. Openings reaching the outer 50 mm, where longitudinal bars lie, have $\ell_M\ge0.5\,b_h/b$, and openings deeper than $h/3$ count as large openings [@ahmed2012] with $\ell\ge0.15$.
- *Steel I-sections*: the lost plastic modulus over flanges and web, $\ell_M=Z_{\mathrm{lost}}/Z$, and the fraction of web depth removed for shear; deep web openings near supports are flagged [@darwin1990].
- *Open-web joists*: the fraction of joist material within the clash slice, attributed to the chords or the web by its position in the depth.
- *Columns, braces, walls and foundations*: the fraction of cross-sectional area (columns and braces, $f_N=1$), of wall length (weighted 1.0 within the boundary zones and 0.6 elsewhere) or of plan area removed.
- *Slabs*: an embedded horizontal run has $\ell=0.375\,D_{\mathrm{MEP}}/t$, so $\eta=0.125$ at ACI's limit of $t/3$ [@aci2019]. A penetration is assessed for punching when it lies within $4t$ of a column face and for flexure with demand factors of 1.0, 0.5 and 0.1 by column and middle strips, following ACI 318 §8.5.4.

Clearance clashes and touches have $\eta=0$. The consequence level uses bay-equivalents, $n_D=D/D_{\mathrm{ref}}$ and $n_E=E/D_{\mathrm{ref}}$: C3 (global) if $n_D\ge15$ or $n_E\ge5$, C2 (extended) if $n_D\ge3$ or $n_E\ge1$, and C1 (local) otherwise. The impact level (L0: $\eta<0.05$; L1: $<0.15$; L2: $<0.35$; L3: $\ge0.35$) and the consequence level index a risk matrix (Table 2) that returns *Negligible*, *Minor*, *Major* or *Critical*; clearance clashes are classed as *Coordination*. Within and across classes, clashes are ranked by

$$s=\eta\,\frac{1+\beta\,\mathrm{LPCI}}{1+\beta}, \qquad \beta=2, \qquad (4)$$

so that equal local damage ranks higher on a more critical member. The thresholds are judgement-based and are tested in the sensitivity analysis (Section 5.4).

Table: Table 2. Severity matrix (impact level × consequence level). {#tbl:matrix}

| Impact \\ Consequence | C1 local | C2 extended | C3 global |
|---|---|---|---|
| L0 ($\eta<0.05$) | Negligible | Negligible | Minor |
| L1 ($0.05\le\eta<0.15$) | Minor | Minor | Major |
| L2 ($0.15\le\eta<0.35$) | Minor | Major | Critical |
| L3 ($\eta\ge0.35$) | Major | Critical | Critical |

## Digital-twin synchronisation

The twin holds the current elements, an R-tree of MEP boxes, the cached contact pairs, the clashes and their assessments, and records every version in SQLite, with a SHA-1 fingerprint of each element's rounded mesh, properties and category. A pyRevit hook on Revit's `DocumentChanged` event serialises the added and modified elements of each committed transaction, with the ids of deleted ones, into the twin's inbox. For each delta the twin diffs fingerprints, removes the affected clashes, and re-runs the narrow phase only for changed structural × all MEP and all structural × changed MEP elements. If a structural member changed, it recomputes that member's contacts before re-orienting and re-propagating the graph, and it re-assesses all clashes, because support sets can move. The result is designed to be identical to a full recomputation, and this is tested (Section 5.5). A *Show Severity* command writes the results back: it colours each clashing structural member in the active view by its worst class and places a marker recording the class, $\eta$ and LPCI at every Critical and Major clash. The coupling between the authoring model and the analysis is therefore automatic in both directions [@kritzinger2018].

# Implementation and evaluation design

## Implementation

The Revit side is a pyRevit [@pyrevit] extension for Revit 2027 (.NET 10, IronPython 2.7) with three ribbon commands (*Export Twin*, *Twin Sync*, *Show Severity*) and the change hook; API use was checked against a reference generated from the installed API assemblies [@revitapi2027]. The analysis service is a Python 3.11 package that uses trimesh and Manifold, python-fcl [@pan2012], an R-tree, NetworkX [@hagberg2008] and SQLite, and all experiments ran on one Windows 11 workstation. An automated test suite contains synthetic cases with known answers (a one-bay frame with hand-checkable loads, a pipe through a beam with an analytical intersection volume, an embedded conduit) and incremental-versus-full equivalence checks.

A generative AI coding agent, Claude Code with the Claude Opus 5.5 model (Anthropic), wrote the extension, the analysis package, the experiment scripts and the scripts that produce the figures, the tables and the architecture diagram, under the authors' direction; it also ran the experiments and searched the literature through the OpenAlex API. Its output was verified independently of the agent: by the test suite, by agreement with Revit's own solid-intersection filter, by exact load equilibrium in both models and by identity of incremental and full recomputation. Every number, table and plot is generated by the released scripts from the stored results, and every reference was checked against its DOI record.

## Case-study models

Two federated models distributed with Revit 2027 were used (Table 3). *Snowdon Towers* combines steel W-shape girders, open-web steel joists, concrete beams, columns, walls and slabs on spread footings, with separate architectural, HVAC, plumbing, electrical and site models. *Golden Nugget* has a combined architectural and structural model and a building-services model. In each case the structural model was opened as host with the other models as links, detached and read-only, and nothing was saved.

<!--TABLE3-->

Snowdon Towers was the *development* case: errors found while analysing it led to the corrections reported with the detection and load-path results. The method was then frozen and applied to Golden Nugget as a *held-out* case, which exposed assumptions that did not generalise and one reproducibility defect. The following were revised and re-applied to **both** models: (i) the reference bay load $D_{\mathrm{ref}}$; (ii) the beam–column and brace orientation rules; (iii) the reinforcement-zone rule, now restricted to concrete; and (iv) the handling of open components. Section 5.6 compares the frozen and revised results; all other results use the revised method, which changed three classes in the development case.

## Evaluation design

- **RQ1, detection.** Physical clashes (hard and touch) were compared with the pairs returned by Revit's `ElementIntersectsSolidFilter`, and every disagreement was inspected. Broad-phase scalability was measured by tiling a model $k$ = 1, 2, 4 and 8 times.
- **RQ2, load path.** Global equilibrium, unsupported members and the distribution of carried loads were examined.
- **RQ3, severity.** The proposed classes were compared with (i) *local impact only*, the same $\eta$ with every member at the middle consequence level (a load-path ablation); (ii) *geometry only*, classes from the smallest clash extent with thresholds of 10, 50 and 150 mm, as in penetration-depth triage; and (iii) *category rules*, a priority by member type (column > beam, wall, foundation > slab), raised one level for MEP elements of 300 mm or more. A one-at-a-time sensitivity analysis varied the impact and consequence thresholds (×0.5 to ×2), α, β, the loads and the tolerances, reporting the Jaccard overlap of the Critical+Major set, the quadratic-weighted Cohen's κ of the classes and Kendall's τ of the top-50 scores.
- **RQ4, digital twin.** A seeded stream of 120 changes (20 each of MEP move, resize, add and delete, and beam move and delete) was applied through the twin; every 20 events, the incremental state was compared with, and timed against, a full recomputation.

# Results

## Clash detection (RQ1)

Snowdon Towers has 1,185 structural members (959 beams, 54 columns, 90 foundations, 58 walls and 24 slabs) and 9,129 MEP elements in three links (HVAC 2,118; electrical 852; plumbing 6,159). The framework found 687 hard clashes, 17 touches and 592 clearance clashes (Table 4). Of the hard clashes, 602 involved slabs, mostly pipes and conduits through floors, and clearance clashes concentrated on beams (478), where ducts and pipes run just beneath the framing.

<!--TABLE4-->

Revit's filter returned 697 pairs, of which 696 were found (recall 0.999), and 8 of the 704 physical clashes were not in Revit's set (precision 0.989). All 8 are zero-volume face contacts, which Revit's filter excludes by definition, and the single miss is a pipe whose tessellation stops short of a slab face. During development, surface-only collision tests missed 59 MEP elements lying entirely inside slabs or walls (recall 0.914 before the containment test was added), and a sampling fallback underestimated intersection volumes in the non-watertight open-web joists by up to a factor of 2.6, whereas the component-wise Boolean is exact and deterministic. The R-tree reduced the 10.8 million structural–MEP pairs to 2,040 candidates in 0.09 s. With the model tiled eight times (692 million pairs), the brute-force broad phase grew quadratically to 45 s and the R-tree almost linearly to 0.84 s (Fig. 2a). The complete pipeline (detection 17 s, load-path graph 17 s, severity 5 s) took 39 s, against 544 s for Revit's filter (Fig. 2b), although that advantage does not hold for every model (Section 5.6).

![Fig. 2. Detection efficiency. (a) Broad-phase time against the number of structural–MEP element pairs when Snowdon Towers is tiled k = 1, 2, 4, 8 times; candidate sets are identical. (b) End-to-end time of the proposed pipeline and of Revit's ElementIntersectsSolidFilter.](figures/fig2_detection.png){#fig:det width=75%}

## Load-path graph (RQ2)

The graph of Snowdon Towers has 1,185 member nodes and 3,432 support edges from 4,059 contact pairs, and only one directed cycle had to be broken (Fig. 3). The reference bay load is $D_{\mathrm{ref}}=51$ kN. Beams, most of which are joists, cluster around it, whereas walls, columns and foundations carry one to two orders of magnitude more, up to 14.1 MN. The total factored load of 114.2 MN enters the ground exactly (ratio 1.0000). With mesh contact alone, 60 members (5.1 %) had no path to the ground, mostly W18x55 girders whose steel geometry is cut back at the connections; member-end proximity reduced this to 21, and the revised beam–column rule to 18 (1.5 %). These are 17 short steel beams and channels and one wall with no modelled support, which the framework flags as modelling gaps.

![Fig. 3. Load-path graph of Snowdon Towers. (a) Members shaded by the factored load they carry (log scale; darker means more load); thin lines are support edges; open circles mark the 18 members with no path to the ground. (b) Carried load by member type; bars show the median and interquartile range; loads below 1 kN are shown at 1 kN.](figures/fig3_loadpath.png){#fig:lp width=80%}

## Severity classification (RQ3)

Of the 687 hard clashes in Snowdon Towers, the proposed method rated 1 Critical, 11 Major, 96 Minor and 579 Negligible (Fig. 4 and Table 5). Geometry-only triage rated 43 Critical and 344 Major, so 387 clashes (56 %) would need priority attention, and category rules rated 4 Critical and 83 Major. Agreement with the proposed classes is close to chance for geometry-only triage (quadratic-weighted κ = 0.03) and low for category rules (κ = 0.15), and the methods disagree in both directions (Fig. 5). Of the 387 clashes that geometry-only triage would prioritise, 349 are slab penetrations, mostly vertical pipes through the floor plate that would normally be sleeved; the proposed method rated 320 of the 387 Negligible and 62 Minor, because the openings are small relative to the column strip and the punching perimeter and the local panel load is small. Conversely, 7 of the 12 clashes that the proposed method rated Critical or Major were only Minor for geometry-only triage, such as a 203 mm duct clipping the bottom flange of a W-shape girder (Fig. 6b) and mechanical units cutting the chords of open-web joists (Fig. 6c).

<!--TABLE5-->

The single Critical clash is a 273 mm pipe running inside a foundation that carries about 5 MN, or 100 bay-equivalents (Fig. 6a); its local impact alone ($\eta=0.20$) would make it Major. The load-path ablation produced 11 Critical or Major clashes. The consequence level downgraded two of them (chord cuts in joists carrying about one bay) and upgraded three: small pipes through heavily loaded walls (16–35 bays) and a pipe embedded in a slab directly beneath a wall that has no other support (orphaned load 1.8 MN).

![Fig. 4. Distribution of severity classes of the hard clashes under the four classification methods. "C+M" is the number of Critical and Major clashes.](figures/fig4_severity.png){#fig:sev width=80%}

![Fig. 5. Cross-tabulation of geometry-only and proposed classes for the hard clashes.](figures/fig5_crosstab.png){#fig:xtab width=70%}

![Fig. 6. Examples from Snowdon Towers (isometric view and view along the structural member). (a) A pipe running inside a heavily loaded foundation. (b) A duct clipping the bottom flange of a steel girder. (c) A mechanical unit cutting the chord zone of an open-web joist. (d) A large elbow in a slab on grade, Critical for geometry-only triage but structurally negligible.](figures/fig6_examples.png){#fig:ex width=75%}

## Sensitivity (RQ3)

In Snowdon Towers the classification is insensitive to the consequence thresholds (κ~w~ ≥ 0.97 for scaling between 0.5 and 2), to the loads (κ~w~ ≥ 0.99) and to the tolerances (κ~w~ = 1.00) (Fig. 7). The weights α and β change no class, by construction, but reorder the ranking within classes (Kendall's τ of the top 50 between 0.73 and 0.98). In both models the impact thresholds matter most: scaling them by 0.67 raises the Critical+Major set from 12 to 19 in Snowdon Towers and from 15 to 30 in Golden Nugget, and scaling by 1.5 reduces it to 6 and 2 (Jaccard 0.13–0.67, κ~w~ 0.76–0.94). Golden Nugget is also sensitive to halving the consequence thresholds (28 Critical+Major, κ~w~ 0.62), because many of its walls carry one to three bay-equivalents, and to doubling the contact tolerance to 100 mm (28, κ~w~ 0.63), because more timber joints then count as supports. These parameters most need calibration against expert judgement.

![Fig. 7. One-at-a-time sensitivity of the severity classification (circles: Snowdon Towers; squares: Golden Nugget). (a) Jaccard overlap of the Critical+Major set, (b) quadratic-weighted κ of the four classes, and (c) Kendall's τ of the top-50 scores, each relative to the reference configuration.](figures/fig7_sensitivity.png){#fig:sens width=80%}

## Digital-twin performance (RQ4)

The initial synchronisation of Snowdon Towers took 38 s. Over the 120 design changes, incremental updates took a median of 62 ms for MEP changes (95th percentile 143 ms) and 5.6 s for structural changes (95th percentile 6.4 s), against 23–27 s for a full recomputation (Fig. 8), so MEP changes were processed about 400 times faster. Structural updates are dominated by re-propagating loads (median 2.4 s) and by conservatively re-assessing every clash (3.2 s). At all six checkpoints the incremental state was identical to the full recomputation, with the same clash pairs, kinds, classes and $\eta$ to six decimals. Supplementary Video 1 shows the loop in Revit for one change: lowering a W18x86 beam by 150 mm created three hard clashes on it (Critical, Major and Minor), which appeared in the severity view 6.9 s after the edit (3.1 s in Revit and 3.4 s in the twin service), and restoring the beam returned the model to its 1,296 clashes.

![Fig. 8. Incremental update latency of the digital twin for 120 design changes per model; horizontal bars are medians, the dashed lines are the mean times of a full recomputation.](figures/fig8_twin_latency.png){#fig:twin width=65%}

## Held-out case: Golden Nugget

Golden Nugget is structurally unlike Snowdon Towers: concrete walls, slabs and foundations carry a timber skeleton frame (posts with tenon joints, transoms, purlins and braces) together with steel HEB beams and columns. Its 637 structural members comprise 277 beams, 59 braces, 139 columns, 102 walls, 45 slabs and 15 foundations, with 5,297 MEP elements (Table 3).

**Detection.** The framework found 338 hard clashes, 31 touches and 715 clearance clashes and, against Revit's 357 reference pairs, achieved precision 0.962, recall 0.994 and F1 0.978 (Table 4). Of the 14 pairs not in Revit's set, 10 are touches and 4 are small overlaps (1.6–22.5 cm³); the 2 pairs Revit reports but the framework does not are measured 11 and 20 mm apart, a discrepancy that could not be resolved from the exported geometry. Detection took 46 s, longer than the 32 s Revit needed, because detailed equipment families must be intersected component by component. The run also exposed a reproducibility defect: open components fell back to point sampling with unseeded random rays, so the twin's incremental state differed from a full recomputation in 14 of 1,079 clash values. Convex-hull stand-ins and the fixed-direction parity test made all results reproducible.

**What the frozen method got wrong** (Table 6). (1) The reference bay load, then defined as the median beam load, collapsed to 0.3 kN, because in this flat-slab building the floors bear directly on walls and columns and the framing members receive little floor load. Nearly every member therefore fell into the global consequence level, and 65 hard clashes (19 %) were rated Critical or Major, almost twice the 35 of the local-impact ablation. (2) Ninety members (14 %) had no path to the ground. Most were timber posts whose tenons sink about 100 mm into the sill beams they stand on, so the rule "a beam whose end reaches a column bears on it" reversed the support, and long diagonal braces were treated as supports.

**Revision, applied to both models.** $D_{\mathrm{ref}}$ was redefined as the median load a member receives directly from a slab, which does not depend on how the floors are supported: 45.7 kN here and 51.0 kN (previously 54.4 kN) in Snowdon Towers. The beam–column rule now asks whether the vertical member continues below the beam, and braces never support gravity load (Table 1). The unsupported set fell to 53 members (8.3 %): 28 timber beams, 18 slabs, 6 walls and 1 column, whose supports the rules cannot infer from the modelled joinery. In Snowdon Towers the revision changed the unsupported set from 21 to 18 members and the class of three of the 687 hard clashes. Load was conserved exactly in both models (27.4 MN in Golden Nugget).

<!--TABLE6-->

**Severity.** With the revised method, 15 of the 338 hard clashes (4.4 %) were rated Major, 126 Minor and 197 Negligible, with none Critical (Table 5). Geometry-only triage would prioritise 111 clashes (33 %) and category rules 263 (78 %), with κ~w~ = 0.07 and 0.06. The load path mattered more than in Snowdon Towers: it downgraded 23 of the 35 Critical or Major clashes of the local-impact ablation, all in lightly loaded members (9 walls, 6 timber purlins, 5 slab panels and 3 braces), and upgraded 3. The highest-ranked clashes are a 660 mm duct through a slab ($\eta=1.0$), four ducts and fittings cutting walls within their boundary zones ($\eta$ = 0.42–0.48) and a pipe fitting at the support of a timber purlin (shear, $\eta=0.39$). The wall and brace downgrades rest on gravity load only (Section 6.2).

**Digital twin.** The incremental state was again identical to the full recomputation at all six checkpoints. MEP changes took a median of 37 ms (95th percentile 77 ms) and structural changes 2.5 s (95th percentile 3.5 s), against 23–29 s for a full recomputation; the initial synchronisation took 60 s.

# Discussion

## Implications for coordination practice

<!--DISC1-->

## Validity and limitations

**Severity has not yet been validated against expert judgement.** The classes rest on simplified mechanics and code provisions; the case studies show how they differ from geometry- and category-based triage, not that they are correct. The impact thresholds matter most and should be calibrated against expert ratings, for which a blinded rating instrument is released with the code. Until then, the classes are a transparent prioritisation aid, not a substitute for an engineer's check.

**The mechanics are deliberately simple.** Demand shapes assume simply supported members under uniform load, capacities are fractions of the gross section because reinforcement and connection details are rarely modelled, and only gravity loads are considered. The lateral role of walls and braces is therefore not captured. This matters because, in the held-out case, 12 of the 23 Critical or Major clashes the load path downgraded were in walls or braces; the wall boundary-zone flag keeps such clashes visible. A finite-element check of the highest-ranked clashes is a natural next step.

**The load path inherits the quality of the model.** Supports are inferred from geometry, joins and member ends with fixed tolerances, and unsupported members are reported rather than guessed. For the 8.3 % of members left unsupported in the held-out case, mostly timber beams and slabs, the consequence is underestimated, and further structural systems (precast, cross-laminated timber, long-span trusses) may need additional orientation rules.

**Reference, scope and generalisability.** Detection is compared with Revit's solid filter, an exact but independent implementation, not with ground truth. The twin couples the authoring model, not the physical building. Two sample models of one authoring platform were analysed, and the held-out one was also used to revise two rules, so it is no longer an unbiased test; real coordination datasets with documented decisions are needed.

# Conclusions

<!--CONCL-->

# Declarations {.unnumbered}

**CRediT authorship contribution statement.** **Muhammad Ahmed:** Conceptualization, Software, Investigation, Resources, Project administration, Writing – review & editing. **Maleeha Waseem:** Conceptualization, Methodology, Visualization, Writing – original draft, Writing – review & editing. **Muhammad Arham:** Data curation, Formal analysis, Validation, Writing – review & editing.

**Funding.** This research did not receive any specific grant from funding agencies in the public, commercial, or not-for-profit sectors.

**Declaration of competing interest.** The authors declare that they have no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper.

**Data availability.** The source code (the pyRevit extension and the Python analysis package), the experiment scripts, the result tables and the expert rating instrument are openly available on GitHub at <https://github.com/Darkiii-2514/DT-Clash-Detection-Paper>. The case-study models are Autodesk Revit 2027 sample files that are installed with the software and are not redistributed. The raw model exports can be regenerated from them with the released extraction scripts.

**Declaration of generative AI and AI-assisted technologies in the manuscript preparation process.** During the preparation of this work the authors used Claude Code with the Claude Opus 5.5 model (Anthropic) to search the literature, format the references and draft and revise the manuscript text, highlights and captions. The use of the same tool for software development and data analysis is described in Section 4.1. After using this tool, the authors reviewed and edited the content as needed and take full responsibility for the content of the published article.

# References {.unnumbered}

::: {#refs}
:::
