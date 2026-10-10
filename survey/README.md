# Expert rating study (severity validation)

The paper's severity classes are a transparent, code-informed prioritisation, but they have **not yet been validated against engineers' judgement**. This kit lets you run that validation. The paper is much stronger for *Automation in Construction* reviewers with it than without it.

## What is in the kit

- `Severity_Rating_Form.xlsx`: one row per clash, with two 3D views, the structural member, the MEP element, the clash geometry and the load context, plus a dropdown for the rating (Negligible / Minor / Major / Critical) and confidence (1–5).
- `images/`: the snapshots embedded in the form.
- `answer_key.csv`: what each method said about each item. **Do not send this to raters.**

The form never shows any method's classification, so the raters are blind to it.

## How to run it

1. **Raters:** 3–5 practising structural engineers, or structural academics with design experience. More raters give a more reliable consensus. Record each rater's role and years of experience on the *Instructions* sheet.
2. **Ethics:** check whether your university needs ethics or IRB approval for an expert survey. Many do not for anonymous professional judgement, but some do. Get each rater's consent to use their anonymised ratings.
3. Send each rater a **copy** of the form. Ask them to work independently and not to discuss items until all forms are returned. Expect about 40–60 minutes for the 48 items.
4. Save the returned forms as `survey/returned/<rater-id>.xlsx`.
5. Run the analysis:

   ```bash
   .venv\Scripts\python experiments\analyse_survey.py survey\returned\*.xlsx
   ```

   It reports inter-rater reliability (Krippendorff's α, ordinal; mean pairwise weighted κ) and the consensus (median) rating per item. For each method (proposed, local-only ablation, geometry-only, category rules) it reports the weighted κ, exact agreement and Spearman ρ against the consensus, plus Critical/Major precision and recall. Results go to `survey/agreement.csv` and `survey/consensus.csv`.

## Reporting

Add a subsection *"Expert evaluation"* under Results, with a table of `agreement.csv`, and report α. If the impact thresholds disagree systematically with the experts, the sensitivity analysis shows which way to move them. Recalibrate on half the items, report agreement on the other half, and say so in the paper.
