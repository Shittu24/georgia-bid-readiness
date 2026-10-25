# Import the approved hotel-pilot review

This package records the user's explicit conversation approval: "I also approve... everything is good". The decisions are 14 accepted with the reviewed corrections, 15 rejected, and 3 needs_followup. It does not claim an independent human annotation exercise: review_method is human because the human approved the decisions; audit notes identify the process as assistant_aided_human_approval and preserve the assistant rationale.

No schema migration or new dependencies are required beyond the previous loader packages. Existing candidate rows, raw predictions, original evidence-match flags, frozen annotations and evaluation scores remain unchanged. Accepted payloads are stored separately in core.requirement_reviews. This does not automatically create canonical groups or amendment edges. The three combined addendum instructions are not silently split.

## Approval artifacts

data/reviews/hotel_pilot_review_v1 contains the approved decision manifest, its SHA-256 sidecar, and the exact source review packet. Keep these files with the project backup. The timestamp is when the approval was recorded in the package, not an invented exact timestamp for the user's chat message; audit notes explicitly explain that distinction.

Checksums detect accidental edits and support provenance, but are not digital signatures or independent authentication. Authorization comes from the explicit user approval. Do not edit this applied batch to change a decision: make a new review batch with the expected prior event ID and a newer recording time.

## Validation behavior

Before writing, the importer checks package/source hashes, decision coverage, approval metadata, accepted payload structure, candidate prediction and artifact hashes, exact extracted-page provenance/text, and accepted evidence quotes against their claimed supplied pages. At least one accepted quote must cite the target page. Semantic correctness comes from the approved review, not substring matching.

All writes are one transaction. The importer briefly locks the review table against concurrent writes while checking prior review state. An existing unexpected review blocks a first-time import and rolls back the batch. Stable event IDs make reimport safe; changed contents under the same ID are rejected. Reimporting an already-recorded review after a later review exists does not reactivate it; historical reuse is reported separately.

Preview runs the database checks and rolls back. Reports are written to reports/review_imports after successful preview or commit. Every event's notes include the decision package hash, source packet hash, batch ID, approval evidence, process, timestamp explanation and rationale.

## School CPU commands

```bash
cd /home/jovyan/project/georgia-bid-readiness
GBR_RUN_DB_TESTS=1 /opt/conda/bin/python -m pytest tests/test_review_importer.py -v
/opt/conda/bin/python scripts/import_candidate_reviews.py
```

Expect 10 tests passed and a preview ending `Mode: preview_rolled_back` with 32 reviews, accepted=14, rejected=15, needs_followup=3. Those preview insert counts describe rolled-back writes.

If the preview matches:

```bash
/opt/conda/bin/python scripts/import_candidate_reviews.py --commit
/opt/conda/bin/python scripts/import_candidate_reviews.py --commit
```

The first command records 32 events. The second must report reviews_reused=32 with no inserted events. Stop if any command reports an error; do not modify the manifest just to bypass a validation failure.

## Verification performed before delivery

Ten new tests passed on local PostgreSQL 18: preview rollback, committed repeat import, tampered package, missing approval, duplicate decisions, wrong evidence, changed source provenance, concurrent/prior-state conflict with whole-batch rollback, changed reimport conflict, and historical reuse without overriding a newer decision.

The actual 32-decision package was also replayed against synthetic source records populated from the exported warehouse packet, alongside the original pilot response artifacts. Preview, commit and repeat all passed, with 14/15/3 statuses in the review view. The whole local replay was rolled back. The school database was not accessed from this machine; the school preview performs that remaining check.

The new review-importer.yml CI workflow is additive and uses PostgreSQL 17. It runs synthetic tests, not the approved real batch. It has not yet run on GitHub. Existing workflows are preserved.
