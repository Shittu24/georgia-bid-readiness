-- Applied transactionally by scripts/apply_requirement_schema.py.
-- Existing core tables and their rows are not changed.

CREATE TABLE core.model_runs (
    model_run_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    approach TEXT NOT NULL,
    config_sha256 TEXT NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
    configuration JSONB NOT NULL CHECK (jsonb_typeof(configuration) = 'object'),
    dataset_snapshot_id TEXT,
    artifact_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row per actual model call, including failures and retries.
-- response_id is assigned from a persistent artifact identity, not load time.
CREATE TABLE core.model_responses (
    response_id TEXT PRIMARY KEY,
    model_run_id TEXT NOT NULL REFERENCES core.model_runs(model_run_id),
    split TEXT NOT NULL CHECK (split IN ('development','evaluation','operational')),
    status TEXT NOT NULL CHECK (status IN ('completed','failed')),
    raw_response TEXT,
    parsed_response JSONB,
    json_valid BOOLEAN NOT NULL,
    schema_valid BOOLEAN NOT NULL,
    error_message TEXT,
    generation_seconds DOUBLE PRECISION CHECK (
        generation_seconds >= 0 AND generation_seconds < 'Infinity'::float8
    ),
    input_tokens INTEGER CHECK (input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens >= 0),
    output_budget_reached BOOLEAN NOT NULL,
    receipt_id TEXT,
    receipt_path TEXT,
    artifact_path TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (response_id, schema_valid),
    CHECK (NOT schema_valid OR json_valid),
    CHECK (NOT schema_valid OR
           (parsed_response IS NOT NULL AND jsonb_typeof(parsed_response) = 'array')),
    CHECK (status <> 'completed' OR raw_response IS NOT NULL),
    CHECK (status <> 'failed' OR (NOT schema_valid AND error_message IS NOT NULL))
);

-- Actual input pages: full extraction-run/document/page provenance.
-- Document hash is obtained through the existing page_extractions row.
CREATE TABLE core.response_pages (
    response_id TEXT NOT NULL REFERENCES core.model_responses(response_id),
    input_position INTEGER NOT NULL CHECK (input_position > 0),
    page_role TEXT NOT NULL CHECK (page_role IN ('target','context')),
    extraction_run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    text_sha256 TEXT NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (response_id, input_position),
    UNIQUE (response_id, extraction_run_id, document_id, page_number),
    FOREIGN KEY (extraction_run_id, document_id, page_number)
      REFERENCES core.page_extractions(extraction_run_id, document_id, page_number)
);
CREATE UNIQUE INDEX response_one_target
    ON core.response_pages(response_id) WHERE page_role = 'target';

-- A structurally valid prediction is only a candidate, never an approval.
CREATE TABLE core.requirement_candidates (
    candidate_id TEXT PRIMARY KEY,
    response_id TEXT NOT NULL,
    response_schema_valid BOOLEAN NOT NULL DEFAULT TRUE CHECK (response_schema_valid),
    output_index INTEGER NOT NULL CHECK (output_index > 0),
    requirement_text TEXT NOT NULL CHECK (length(btrim(requirement_text)) > 0),
    condition_text TEXT,
    deadline_text TEXT,
    original_prediction JSONB NOT NULL CHECK (jsonb_typeof(original_prediction) = 'object'),
    UNIQUE (response_id, output_index),
    UNIQUE (candidate_id, response_id),
    FOREIGN KEY (response_id, response_schema_valid)
      REFERENCES core.model_responses(response_id, schema_valid)
);

-- Preserve wrong citations as evidence claims. A missing mapping is allowed;
-- an existing mapping must refer to a page actually supplied to this call.
CREATE TABLE core.requirement_evidence (
    candidate_id TEXT NOT NULL,
    response_id TEXT NOT NULL,
    evidence_index INTEGER NOT NULL CHECK (evidence_index > 0),
    claimed_page_number INTEGER NOT NULL CHECK (claimed_page_number > 0),
    quote_text TEXT NOT NULL CHECK (length(btrim(quote_text)) > 0),
    mapped_input_position INTEGER,
    exact_quote_match BOOLEAN NOT NULL,
    validation_notes TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (candidate_id, evidence_index),
    FOREIGN KEY (candidate_id, response_id)
      REFERENCES core.requirement_candidates(candidate_id, response_id),
    FOREIGN KEY (response_id, mapped_input_position)
      REFERENCES core.response_pages(response_id, input_position),
    CHECK (NOT exact_quote_match OR mapped_input_position IS NOT NULL)
);

CREATE FUNCTION core.check_requirement_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE actual_page INTEGER; source_text TEXT;
BEGIN
    IF NEW.mapped_input_position IS NOT NULL THEN
        SELECT rp.page_number, pe.clean_text INTO actual_page, source_text
        FROM core.response_pages rp JOIN core.page_extractions pe
          USING (extraction_run_id, document_id, page_number)
        WHERE rp.response_id = NEW.response_id
          AND rp.input_position = NEW.mapped_input_position;
        IF NOT FOUND OR actual_page <> NEW.claimed_page_number THEN
            RAISE EXCEPTION 'Evidence mapping does not match claimed input page';
        END IF;
        IF NEW.exact_quote_match IS DISTINCT FROM
           (COALESCE(strpos(source_text, NEW.quote_text), 0) > 0) THEN
            RAISE EXCEPTION 'Evidence exact-match flag disagrees with source';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_requirement_evidence
BEFORE INSERT OR UPDATE ON core.requirement_evidence
FOR EACH ROW EXECUTE FUNCTION core.check_requirement_evidence();

-- Append-only decisions; corrections create a new review event.
-- approved_payload is a reviewed snapshot, not a readiness determination.
CREATE TABLE core.requirement_reviews (
    review_event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES core.requirement_candidates(candidate_id),
    decision TEXT NOT NULL CHECK (decision IN ('accepted','rejected','needs_followup')),
    reviewer TEXT NOT NULL CHECK (length(btrim(reviewer)) > 0),
    review_method TEXT NOT NULL CHECK (review_method IN ('human','assistant','automated')),
    reviewed_at TIMESTAMPTZ NOT NULL,
    recorded_order BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    approved_payload JSONB,
    notes TEXT NOT NULL,
    CHECK (approved_payload IS NULL OR jsonb_typeof(approved_payload) = 'object'),
    CHECK (decision <> 'accepted' OR (
        review_method = 'human' AND approved_payload IS NOT NULL
        AND jsonb_typeof(approved_payload -> 'requirement') = 'string'
        AND COALESCE(length(btrim(approved_payload ->> 'requirement')), 0) > 0
    ))
);
CREATE FUNCTION core.reject_requirement_review_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Review history is append-only; insert a new review event';
END $$;
CREATE TRIGGER immutable_requirement_reviews
BEFORE UPDATE OR DELETE ON core.requirement_reviews
FOR EACH ROW EXECUTE FUNCTION core.reject_requirement_review_mutation();

CREATE INDEX ON core.model_responses(model_run_id);
CREATE INDEX ON core.response_pages(extraction_run_id, document_id, page_number);
CREATE INDEX ON core.requirement_reviews(candidate_id, reviewed_at DESC, recorded_order DESC);

CREATE SCHEMA IF NOT EXISTS reporting;
CREATE VIEW reporting.requirement_review_queue AS
SELECT c.candidate_id, c.response_id, c.requirement_text,
       c.condition_text, c.deadline_text,
       COALESCE(r.decision, 'unreviewed') AS review_status,
       r.reviewer, r.reviewed_at, r.approved_payload,
       evidence.evidence_count, evidence.exact_match_count
FROM core.requirement_candidates c
LEFT JOIN LATERAL (
    SELECT * FROM core.requirement_reviews rr
    WHERE rr.candidate_id = c.candidate_id
    ORDER BY rr.reviewed_at DESC, rr.recorded_order DESC LIMIT 1
) r ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*) AS evidence_count,
           count(*) FILTER (WHERE e.exact_quote_match) AS exact_match_count
    FROM core.requirement_evidence e WHERE e.candidate_id = c.candidate_id
) evidence ON TRUE;
