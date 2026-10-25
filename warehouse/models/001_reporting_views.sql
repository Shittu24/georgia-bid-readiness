
CREATE SCHEMA IF NOT EXISTS reporting;

-- One row per document version.
CREATE OR REPLACE VIEW reporting.document_inventory AS
SELECT
    s.solicitation_id,
    s.agency_name,
    s.solicitation_number,
    s.title,
    d.document_id,
    d.document_type,
    d.amendment_number,
    v.sha256,
    v.page_count,
    v.size_bytes,
    v.local_path,
    observations.observation_count,
    observations.first_retrieved_at,
    observations.last_retrieved_at
FROM core.solicitations AS s
JOIN core.documents AS d
  ON d.solicitation_id = s.solicitation_id
JOIN core.document_versions AS v
  ON v.document_id = d.document_id
LEFT JOIN LATERAL (
    SELECT
        COUNT(*) AS observation_count,
        MIN(o.retrieved_at) AS first_retrieved_at,
        MAX(o.retrieved_at) AS last_retrieved_at
    FROM core.document_observations AS o
    WHERE o.document_id = v.document_id
      AND o.version_sha256 = v.sha256
      AND o.status = 'ok'
) AS observations ON TRUE;

-- One row per extraction run and document version.
CREATE OR REPLACE VIEW reporting.extraction_quality AS
SELECT
    d.solicitation_id,
    p.extraction_run_id,
    p.document_id,
    p.document_sha256,
    COUNT(*) AS page_records,
    COUNT(*) FILTER (
        WHERE p.status = 'ok'
    ) AS successful_pages,
    COUNT(*) FILTER (
        WHERE p.status = 'failed'
    ) AS failed_pages,
    COUNT(*) FILTER (
        WHERE p.needs_review
    ) AS originally_flagged_pages,
    COUNT(*) FILTER (
        WHERE p.needs_review
          AND latest.review_status = 'resolved'
          AND latest.ocr_required = FALSE
    ) AS resolved_flagged_pages,
    COUNT(*) FILTER (
        WHERE p.needs_review
          AND (
              latest.review_status IS DISTINCT FROM 'resolved'
              OR latest.ocr_required IS DISTINCT FROM FALSE
          )
    ) AS unresolved_flagged_pages,
    COALESCE(SUM(p.character_count), 0) AS extracted_characters
FROM core.page_extractions AS p
JOIN core.documents AS d
  ON d.document_id = p.document_id
LEFT JOIN LATERAL (
    SELECT r.review_status, r.ocr_required
    FROM core.page_reviews AS r
    WHERE r.extraction_run_id = p.extraction_run_id
      AND r.document_id = p.document_id
      AND r.page_number = p.page_number
    ORDER BY r.reviewed_at DESC, r.review_id DESC
    LIMIT 1
) AS latest ON TRUE
GROUP BY
    d.solicitation_id,
    p.extraction_run_id,
    p.document_id,
    p.document_sha256;

-- One row per recorded ingestion or extraction run.
CREATE OR REPLACE VIEW reporting.processing_history AS
SELECT
    r.run_id,
    r.run_type,
    r.parent_run_id,
    r.status,
    r.started_at,
    r.completed_at,
    EXTRACT(EPOCH FROM (
        r.completed_at - r.started_at
    )) AS recorded_elapsed_seconds,
    r.artifact_path,
    (
        SELECT COUNT(*)
        FROM core.document_observations AS o
        WHERE o.run_id = r.run_id
    ) AS document_observations,
    (
        SELECT COUNT(*)
        FROM core.page_extractions AS p
        WHERE p.extraction_run_id = r.run_id
    ) AS page_records
FROM core.pipeline_runs AS r;
