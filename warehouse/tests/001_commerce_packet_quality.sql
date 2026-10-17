
WITH
selected_run AS (
    SELECT *
    FROM core.pipeline_runs
    WHERE run_id = %(extraction_run_id)s
      AND run_type = 'extraction'
),
packet_documents AS (
    SELECT *
    FROM core.documents
    WHERE solicitation_id = %(solicitation_id)s
),
expected_versions AS (
    SELECT
        o.document_id,
        o.version_sha256,
        v.page_count
    FROM selected_run AS r
    JOIN core.document_observations AS o
      ON o.run_id = r.parent_run_id
    JOIN packet_documents AS d
      ON d.document_id = o.document_id
    JOIN core.document_versions AS v
      ON v.document_id = o.document_id
     AND v.sha256 = o.version_sha256
    WHERE o.status = 'ok'
),
pages AS (
    SELECT p.*
    FROM core.page_extractions AS p
    JOIN packet_documents AS d
      ON d.document_id = p.document_id
    WHERE p.extraction_run_id = %(extraction_run_id)s
),
coverage AS (
    SELECT
        v.document_id,
        v.version_sha256,
        v.page_count,
        COUNT(p.page_number) AS extracted_pages,
        MIN(p.page_number) AS first_page,
        MAX(p.page_number) AS last_page
    FROM expected_versions AS v
    LEFT JOIN pages AS p
      ON p.document_id = v.document_id
     AND p.document_sha256 = v.version_sha256
    GROUP BY v.document_id, v.version_sha256, v.page_count
),
flag_reviews AS (
    SELECT
        p.document_id,
        p.page_number,
        latest.review_status,
        latest.ocr_required
    FROM pages AS p
    LEFT JOIN LATERAL (
        SELECT review_status, ocr_required
        FROM core.page_reviews AS r
        WHERE r.extraction_run_id = p.extraction_run_id
          AND r.document_id = p.document_id
          AND r.page_number = p.page_number
        ORDER BY r.reviewed_at DESC, r.review_id DESC
        LIMIT 1
    ) AS latest ON TRUE
    WHERE p.needs_review = TRUE
),
checks AS (
    SELECT
        '01_run_and_packet_present' AS check_name,
        'Extraction run and complete expected input packet exist' AS description,
        CASE WHEN
            (SELECT COUNT(*) FROM selected_run) = 1
            AND (SELECT COUNT(*) FROM expected_versions)
                = %(expected_addenda)s + 1
        THEN 0 ELSE 1 END::bigint AS failure_count

    UNION ALL

    SELECT
        '02_original_count',
        'Exactly one original solicitation is registered',
        CASE WHEN (
            SELECT COUNT(*) FROM packet_documents
            WHERE document_type = 'original'
        ) = 1 THEN 0 ELSE 1 END::bigint

    UNION ALL

    SELECT
        '03_amendment_sequence',
        'Amendments match the expected sequence with no duplicates',
        CASE WHEN
            (SELECT COUNT(*) FROM packet_documents
             WHERE document_type = 'addendum') = %(expected_addenda)s
            AND
            (SELECT COUNT(DISTINCT amendment_number)
             FROM packet_documents
             WHERE document_type = 'addendum'
               AND amendment_number BETWEEN 1 AND %(expected_addenda)s)
                = %(expected_addenda)s
        THEN 0 ELSE 1 END::bigint

    UNION ALL

    SELECT
        '04_document_page_coverage',
        'Every input document version has the expected number of pages',
        COUNT(*)::bigint
    FROM coverage
    WHERE extracted_pages <> page_count

    UNION ALL

    SELECT
        '05_page_numbering',
        'Page numbers cover 1 through the expected final page',
        COUNT(*)::bigint
    FROM coverage
    WHERE first_page IS DISTINCT FROM 1
       OR last_page IS DISTINCT FROM page_count
       OR extracted_pages <> page_count

    UNION ALL

    SELECT
        '06_extraction_failures',
        'No pages have extraction errors',
        COUNT(*)::bigint
    FROM pages
    WHERE status <> 'ok'

    UNION ALL

    SELECT
        '07_unresolved_review_flags',
        'Flagged pages have a resolved latest review and no pending OCR',
        COUNT(*)::bigint
    FROM flag_reviews
    WHERE review_status IS DISTINCT FROM 'resolved'
       OR ocr_required IS DISTINCT FROM FALSE

    UNION ALL

    SELECT
        '08_processing_lineage',
        'Parent is an ingestion run and every page matches its observed version',
        (
            CASE WHEN EXISTS (
                SELECT 1
                FROM selected_run AS r
                JOIN core.pipeline_runs AS parent
                  ON parent.run_id = r.parent_run_id
                WHERE parent.run_type = 'ingestion'
            ) THEN 0 ELSE 1 END
            +
            (SELECT COUNT(*)
             FROM pages AS p
             WHERE NOT EXISTS (
                 SELECT 1
                 FROM expected_versions AS v
                 WHERE v.document_id = p.document_id
                   AND v.version_sha256 = p.document_sha256
             ))
        )::bigint
)
SELECT
    check_name,
    description,
    failure_count,
    failure_count = 0 AS passed
FROM checks
ORDER BY check_name;
