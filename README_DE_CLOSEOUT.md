# DE closeout: approved addendum splits

Ibrahim explicitly approved all four separately presented requirements in this conversation: sign Addendum 1, return Addendum 1 with the proposal, sign Addendum 2, and return Addendum 2 with the proposal. Each cites page 1 of its own addendum. The approval package records the exact drafts, original candidate sources, review IDs, and the authorization. Its timestamp is the package recording time, not an invented message timestamp.

## Run on school CPU

Upload `Georgia_Bid_DE_Closeout_v1.zip` and `START_HERE_DE_Closeout.ipynb` to `/home/jovyan/project/georgia-bid-readiness`. Run the installer. It verifies every file and only replaces the two known prior versions of the dbt solicitation summary and DE workflow. It backs those versions up first and rejects unexpected modifications. Then open `notebooks/11_de_closeout.ipynb` and run in order. PostgreSQL must already be running; the same startup commands from the previous DE README apply. No new runtime, GPU, model training or paid API is needed.

The notebook backs up the database, applies additive migration 005, runs regression tests, previews the review import, commits the authorized decisions, verifies repeat safety, refreshes dbt and backups, and exports the closeout report. The DB importer is transactional and rejects changed drafts, sources, origins, parent reviews, or conflicting newer split reviews. A repeat does not write another review. It never rewrites historical predictions or decisions.

## Expected hotel counts

| Metric | Count |
|---|---:|
| Approved split requirements | 4 |
| Pending split requirements | 0 |
| Distinct current canonical requirements | 17 |
| Current source assertions | 18 |
| Combined parent candidates resolved through splits | 3 |
| Outstanding follow-ups for the existing reviewed population | 0 |

Original model candidates remain 32 (14 accepted, 15 rejected and 3 historical needs-followup decisions). Original candidate-review events remain 32. There are four additional **split-review** events and four split assertions; the previous 14 candidate-source assertions remain unchanged. The 17 distinct groups come from the previous 13 plus four new groups. One earlier obligation has two source assertions. Splits are not fabricated additional model predictions or extra true positives in the original evaluation.

The unified current-assertion view prevents simultaneous counting of a combined parent and its active split children. Reopening a split review removes its assertion from the current view and disables the parent's resolved status. Rebuild dbt after review changes. A partial set of accepted children must not be presented as a complete replacement of the parent's obligation. The original approval importer will refuse to overwrite newer decisions; another reviewed migration would be needed for revised wording.

`mart_solicitation_overview` now includes current split assertions in canonical totals. `mart_de_closeout` distinguishes historical parent review labels from outstanding work. No amendment supersession links were inferred: signing different addenda produces separate requirements, not a supersession relationship. The existing amendment subsystem still addresses original candidate assertions; extending amendment links to split assertions is future work if a source requires it.

## Artifacts and routine refresh

Use `scripts/run_de_pipeline.py run` with `.venv-de/bin/python` for routine refresh after migration 005. Run `scripts/export_de_closeout_report.py` afterward for the current pilot-specific closeout check. Reports go to `reports/de_closeout/<timestamp>/`. The closeout report is created after the normal pipeline backup, so download it separately with the pipeline report and backups. The notebook writes a new project archive afterward to include it.

There are now 17 dbt models and 42 data tests. The new CI workflow runs 48 Python tests against PostgreSQL 17 and builds dbt with synthetic data. Local validation uses PostgreSQL 18 and must not be confused with the school or GitHub run; see packaged validation evidence. The four approvals are assistant-aided human decisions, not independent expert labels.

Do not rerun the old notebook 10's fixed count cell expecting zero split reviews or 13 groups after this closeout. Those were the prior-state baseline. Use notebook 11 for current-state verification. Existing dbt tests and the original DE runner remain usable.

## What is complete, and what comes next

This closes the outstanding split decisions in the current DE pilot. It does not imply all requirements in all PDFs have been discovered. Broader source collection, review operations, bidder profiles, AI quality improvement and application integration remain product work. Next: analyze the existing AI baseline's omissions and unsupported claims, improve on development data, then evaluate on new untouched solicitations. Preserve the original evaluation outputs and metrics.

After the notebook passes, download backups and reports, commit the files listed in its final cell, push, and verify CI. Do not commit virtual environments, database dumps, downloaded ZIPs or installation backups.
