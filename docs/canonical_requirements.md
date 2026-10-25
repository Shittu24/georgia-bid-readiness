# Canonical requirements and amendment relationships

Migration 003 adds four tables and two status views. It changes no existing candidates or reviews. Applying it does not approve any of the 32 imported candidates.

## Meaning of each record

| Table | One row represents |
|---|---|
| core.canonical_requirements | A human-defined obligation group within one solicitation, such as submission signature |
| core.canonical_assertions | A specific accepted review of one source candidate linked to that group |
| core.amendment_relations | A proposed supersession, clarification, or conflict from an earlier assertion to a later addendum assertion |
| core.amendment_relation_reviews | An append-only review decision about a proposed relationship |

The original model response, prediction, evidence claims and review payload remain available. Corrections belong in a new requirement review's approved_payload, not in the original prediction. Two candidates that express the same obligation can be grouped without deleting their separate provenance.

Canonical assertions require the latest candidate review to be accepted and identified as human. Every quote in the reviewed payload must match a supplied target/context page, and the group must belong to the same solicitation as the candidate's target document. Quote existence is not semantic correctness: the human must still check the requirement, conditions, dates and scope against the PDF.

A relationship must join assertions in the same canonical group. Its later endpoint must come from an addendum with a higher amendment number than the earlier endpoint (original documents count as zero). This prevents reversed edges and cycles within this ordering. It does not prove that the later text actually changes the obligation; that requires human review. Document numbering correctness remains an ingestion-quality responsibility.

## Status and corrections

reporting.canonical_assertion_status includes source document hash, extraction run, page and approved payload. review_is_current becomes false if a newer review exists, even if the newer review is also accepted: create a new assertion linked to that new review to use the corrected wording.

reporting.amendment_relation_status reports unreviewed/confirmed/rejected/needs_followup and whether both source reviews are current. usable_reviewed_relation is true only for a confirmed relationship with current endpoint reviews. It is not a bid-readiness result or an automatically selected effective requirement. Multiple relationships may remain conflicting and need resolution.

History is append-only. Correct a mistaken decision with another review event. To correct a grouping, record a fresh review of the candidate and link the new review to the correct group; the old assertion remains historical and its status becomes noncurrent. Confirmations are identified as human by application convention; database fields alone are not authentication.

## Run on the school CPU

Requires migrations 001 and 002, the previous loader package, psycopg, jsonschema and pytest. No GPU or additional dependency installation is needed if the previous tests passed.

```bash
cd /home/jovyan/project/georgia-bid-readiness
/opt/conda/bin/python scripts/apply_canonical_schema.py
/opt/conda/bin/python scripts/apply_canonical_schema.py
GBR_RUN_DB_TESTS=1 /opt/conda/bin/python -m pytest tests/test_canonical_requirements.py tests/test_requirement_loader.py -v
/opt/conda/bin/python scripts/export_candidate_review_packet.py
```

Expected: migration applied then checksum-verified skip; 23 tests passed; 32 unreviewed candidates exported if no candidate reviews have been added since the loader import. Test fixtures are rolled back. The exporter writes a timestamped JSON under reports/candidate_review in a read-only, consistent database transaction. It includes original predictions, claimed evidence, full supplied source pages, PDF paths, document hashes and blank review fields. It does not save review decisions to the database.

The additional canonical-requirements.yml CI workflow builds PostgreSQL 17, applies all three migrations, and runs the 23 tests without changing the earlier workflows. Local validation passed on PostgreSQL 18. School execution and GitHub CI must still be checked separately.

## Next work

Review the exported candidates against their source PDFs, recording corrected payloads or rejections. Then implement and test the transactional review importer and grouping workflow before populating canonical tables. No actual requirement grouping or amendment interpretation has been performed by this schema package. Waivers/withdrawals need an explicit source-annotation path because the current extraction task excludes waivers; they are not represented as automatic deletions. Effective-requirement resolution, conflict resolution, company profiles, readiness assessment and analytical marts remain later increments.
