# Pilot requirements loader

This is the second requirements-warehouse increment. Migration 002 must already be applied. It imports the existing v2 evaluation artifacts without running a model or reading gold labels. It adds no approvals, readiness scores, or amendment resolutions.

## What is checked

- The evaluation configuration hash in every response.
- Frozen evaluation-input bytes against both the configuration and snapshot manifest.
- Prefix and output-schema hashes against the recorded configuration.
- Saved conversation prefix and final user message against the frozen prompt and target/context inputs.
- Coverage of both prompting approaches for every frozen target, with no duplicate jobs.
- JSON parsing, schema validity, and candidate counts recomputed from raw output. Saved flags must agree.
- Exactly one matching successful extraction per document/page. Only outer whitespace is stripped when comparing the database text with frozen input; internal whitespace is not rewritten. If multiple extraction runs match, loading stops instead of selecting a run arbitrarily. An explicit document-to-run JSON mapping may be passed using `--source-runs` after inspecting provenance.
- Exact evidence matching against the claimed target/context page. Few-shot demonstrations are retained in the original response artifact but are not eligible source citations.

Raw invalid outputs remain in model_responses. Their parsed candidates are not salvaged. Schema-valid candidates and incorrect evidence are retained as unreviewed claims. Matching a quote does not establish that the obligation, condition, or deadline is correct.

## Identity, transactions and reports

One model_runs record represents each configuration hash and prompting approach. Response IDs derive from session ID, target-page ID and approach; artifact SHA-256 is compared on reimport. Candidate and evidence identities are positions within that original response. Editing a previously imported artifact causes a conflict rather than an update. Distinct retry sessions can have distinct identities, but this adapter deliberately expects one complete evaluation batch and rejects unexpected formats/statuses.

All inserts are one transaction with an advisory lock. An exception rolls back the batch. The default preview executes the same constraints and rolls back successfully. `--commit` persists the batch. A successful second committed run must report no keys ending `_inserted` with a positive count.

Reports are saved under reports/requirement_loads with configuration, snapshot, per-artifact hashes, source-run overrides and row-operation counts. Keep the original artifacts in project backups. Model run `reused` counts are operations, not distinct configuration counts: one configuration is encountered once per response. No GPU receipt is invented; receipt fields remain unset because this bundle does not include a verifiable receipt. Linking the existing receipt is a later explicit step.

## Run on the school CPU

From /home/jovyan/project/georgia-bid-readiness:

```bash
/opt/conda/bin/python -m pip install --user -r requirements-requirement-loader.txt
/opt/conda/bin/python scripts/load_requirement_pilot.py
```

Preview must finish with `Mode: preview_rolled_back`. Expected for the supplied batch, on first import:

| Item | Count |
|---|---:|
| Configuration/approach records | 2 |
| Model responses | 14 |
| Invalid responses retained | 2 |
| Target/context page links across responses | 22 |
| Requirement candidates | 32 |
| Evidence claims | 32 |
| Exact evidence matches | 10 |
| Nonmatching evidence claims | 22 |

Then commit and check repeat behavior:

```bash
/opt/conda/bin/python scripts/load_requirement_pilot.py --commit
/opt/conda/bin/python scripts/load_requirement_pilot.py --commit
GBR_RUN_DB_TESTS=1 /opt/conda/bin/python -m pytest tests/test_requirement_loader.py -v
```

Tests use unique synthetic fixtures inside rolled-back transactions. They do not modify your original extraction records or approve candidates. Existing tests/test_pipeline.py and its CI workflow are unchanged. The additional .github/workflows/requirement-loader.yml applies schema 001 and migration 002 on PostgreSQL 17, then runs all 11 new tests. Commit the files and inspect that workflow's result before claiming CI passed.

## Validation performed before delivery

Eleven tests passed on a temporary local PostgreSQL 18 database: six artifact/preflight tests and five database tests covering preview rollback, repeat import, incorrect evidence, mid-batch conflict rollback, missing sources and ambiguous sources.

The supplied real artifact bundle also passed preflight and transactional load/reload checks. That local test populated synthetic source rows from the frozen input text; it did not connect to the school database or verify its original PDF/extraction lineage. The school preview performs that remaining source-linkage check. The local test transaction was rolled back and its PostgreSQL server stopped.

## Scope remaining

The loader establishes reproducible storage of the pilot's outputs. Canonical reviewed requirements, addendum precedence, business profiles, bid-readiness assessments, analytical marts, broader data collection, and improved model evaluation remain separate project increments.
