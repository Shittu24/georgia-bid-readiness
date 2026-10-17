
CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.solicitations (
    solicitation_id TEXT PRIMARY KEY,
    agency_name TEXT NOT NULL,
    solicitation_number TEXT NOT NULL,
    title TEXT NOT NULL,
    source_page_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (agency_name, solicitation_number)
);

CREATE TABLE IF NOT EXISTS core.documents (
    document_id TEXT PRIMARY KEY,
    solicitation_id TEXT NOT NULL
        REFERENCES core.solicitations(solicitation_id),
    document_type TEXT NOT NULL
        CHECK (document_type IN (
            'original', 'addendum', 'attachment',
            'bid_results', 'award_notice'
        )),
    amendment_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (document_type = 'addendum'
         AND amendment_number IS NOT NULL
         AND amendment_number > 0)
        OR
        (document_type <> 'addendum' AND amendment_number IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS core.document_versions (
    document_id TEXT NOT NULL
        REFERENCES core.documents(document_id),
    sha256 TEXT NOT NULL
        CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    local_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    page_count INTEGER NOT NULL CHECK (page_count > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_id, sha256)
);

CREATE TABLE IF NOT EXISTS core.pipeline_runs (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL
        CHECK (run_type IN ('ingestion', 'extraction')),
    parent_run_id TEXT REFERENCES core.pipeline_runs(run_id),
    status TEXT NOT NULL
        CHECK (status IN ('running', 'ok', 'partial_failure', 'failed')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    artifact_path TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (
        started_at IS NULL OR completed_at IS NULL
        OR completed_at >= started_at
    )
);

CREATE TABLE IF NOT EXISTS core.document_observations (
    run_id TEXT NOT NULL REFERENCES core.pipeline_runs(run_id),
    document_id TEXT NOT NULL REFERENCES core.documents(document_id),
    version_sha256 TEXT,
    source_url TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    resolved_url TEXT,
    attempted_at TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ,
    http_status INTEGER,
    status TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    storage_action TEXT,
    error_message TEXT,
    PRIMARY KEY (run_id, document_id),
    FOREIGN KEY (document_id, version_sha256)
        REFERENCES core.document_versions(document_id, sha256),
    CHECK (status <> 'ok' OR version_sha256 IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS core.page_extractions (
    extraction_run_id TEXT NOT NULL
        REFERENCES core.pipeline_runs(run_id),
    document_id TEXT NOT NULL,
    document_sha256 TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    extraction_method TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    raw_text TEXT,
    clean_text TEXT,
    character_count INTEGER CHECK (character_count >= 0),
    non_whitespace_characters INTEGER
        CHECK (non_whitespace_characters >= 0),
    quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    needs_review BOOLEAN NOT NULL,
    error_message TEXT,
    PRIMARY KEY (extraction_run_id, document_id, page_number),
    FOREIGN KEY (document_id, document_sha256)
        REFERENCES core.document_versions(document_id, sha256),
    CHECK (jsonb_typeof(quality_flags) = 'array'),
    CHECK (
        status <> 'ok'
        OR (raw_text IS NOT NULL AND clean_text IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS core.page_reviews (
    review_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    extraction_run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    review_status TEXT NOT NULL
        CHECK (review_status IN ('resolved', 'needs_followup')),
    resolution TEXT NOT NULL,
    ocr_required BOOLEAN NOT NULL,
    reviewed_by TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL,
    review_method TEXT NOT NULL,
    notes TEXT NOT NULL,
    FOREIGN KEY (extraction_run_id, document_id, page_number)
        REFERENCES core.page_extractions(
            extraction_run_id, document_id, page_number
        ),
    UNIQUE (
        extraction_run_id, document_id, page_number,
        reviewed_at, reviewed_by
    )
);

CREATE INDEX IF NOT EXISTS idx_documents_solicitation
    ON core.documents(solicitation_id);

CREATE INDEX IF NOT EXISTS idx_observations_version
    ON core.document_observations(document_id, version_sha256);

CREATE INDEX IF NOT EXISTS idx_pages_version
    ON core.page_extractions(document_id, document_sha256);
