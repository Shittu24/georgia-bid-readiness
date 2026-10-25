-- Additive canonical grouping and explicitly reviewed amendment relationships.
-- No existing predictions are promoted and no readiness result is computed.

CREATE TABLE core.canonical_requirements (
    canonical_id TEXT PRIMARY KEY,
    solicitation_id TEXT NOT NULL REFERENCES core.solicitations(solicitation_id),
    topic_label TEXT NOT NULL CHECK (length(btrim(topic_label)) > 0),
    created_by TEXT NOT NULL CHECK (length(btrim(created_by)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One reviewed source assertion within a human-defined obligation group.
-- Corrected wording and evidence remain in the immutable approved_payload.
CREATE TABLE core.canonical_assertions (
    assertion_id TEXT PRIMARY KEY,
    canonical_id TEXT NOT NULL REFERENCES core.canonical_requirements(canonical_id),
    review_event_id TEXT NOT NULL UNIQUE REFERENCES core.requirement_reviews(review_event_id),
    linked_by TEXT NOT NULL CHECK (length(btrim(linked_by)) > 0),
    rationale TEXT NOT NULL CHECK (length(btrim(rationale)) > 0),
    linked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE FUNCTION core.validate_canonical_assertion() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r RECORD; last_event TEXT; group_solicitation TEXT; source_solicitation TEXT;
        response TEXT; claim JSONB; matched BOOLEAN;
BEGIN
    SELECT * INTO r FROM core.requirement_reviews WHERE review_event_id=NEW.review_event_id;
    IF NOT FOUND OR r.decision <> 'accepted' OR r.review_method <> 'human' THEN
        RAISE EXCEPTION 'Canonical assertion requires an accepted human review';
    END IF;
    SELECT review_event_id INTO last_event FROM core.requirement_reviews
      WHERE candidate_id=r.candidate_id ORDER BY reviewed_at DESC, recorded_order DESC LIMIT 1;
    IF last_event IS DISTINCT FROM NEW.review_event_id THEN
        RAISE EXCEPTION 'Canonical assertion cannot use a stale review';
    END IF;
    SELECT solicitation_id INTO group_solicitation FROM core.canonical_requirements WHERE canonical_id=NEW.canonical_id;
    SELECT c.response_id,d.solicitation_id INTO response,source_solicitation
      FROM core.requirement_candidates c JOIN core.response_pages p ON p.response_id=c.response_id AND p.page_role='target'
      JOIN core.documents d ON d.document_id=p.document_id WHERE c.candidate_id=r.candidate_id;
    IF NOT FOUND OR source_solicitation IS DISTINCT FROM group_solicitation THEN
        RAISE EXCEPTION 'Canonical group and source must belong to the same solicitation';
    END IF;
    IF jsonb_typeof(r.approved_payload->'evidence') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Reviewed payload requires an evidence array';
    END IF;
    IF jsonb_array_length(r.approved_payload->'evidence') = 0 THEN
        RAISE EXCEPTION 'Reviewed payload requires at least one evidence quote';
    END IF;
    FOR claim IN SELECT * FROM jsonb_array_elements(r.approved_payload->'evidence') LOOP
        IF jsonb_typeof(claim->'quote') IS DISTINCT FROM 'string'
           OR COALESCE(length(btrim(claim->>'quote')),0)=0
           OR jsonb_typeof(claim->'page_number') IS DISTINCT FROM 'number'
           OR (claim->>'page_number') !~ '^[1-9][0-9]*$' THEN
            RAISE EXCEPTION 'Reviewed evidence needs a positive page number and nonblank quote';
        END IF;
        SELECT EXISTS (
            SELECT 1 FROM core.response_pages p JOIN core.page_extractions e
              USING(extraction_run_id,document_id,page_number)
            WHERE p.response_id=response AND p.page_number::text=claim->>'page_number'
              AND strpos(e.clean_text,claim->>'quote') > 0
        ) INTO matched;
        IF NOT matched THEN
            RAISE EXCEPTION 'Reviewed evidence quote does not match its supplied source page';
        END IF;
    END LOOP;
    RETURN NEW;
END $$;
CREATE TRIGGER validate_canonical_assertion BEFORE INSERT ON core.canonical_assertions
FOR EACH ROW EXECUTE FUNCTION core.validate_canonical_assertion();

CREATE TABLE core.amendment_relations (
    relation_id TEXT PRIMARY KEY,
    earlier_assertion_id TEXT NOT NULL REFERENCES core.canonical_assertions(assertion_id),
    later_assertion_id TEXT NOT NULL REFERENCES core.canonical_assertions(assertion_id),
    relation_type TEXT NOT NULL CHECK (relation_type IN ('supersedes','clarifies','conflicts_with')),
    proposed_by TEXT NOT NULL CHECK (length(btrim(proposed_by)) > 0),
    rationale TEXT NOT NULL CHECK (length(btrim(rationale)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (earlier_assertion_id <> later_assertion_id),
    UNIQUE (earlier_assertion_id,later_assertion_id,relation_type)
);

CREATE FUNCTION core.validate_amendment_relation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE earlier RECORD; later RECORD;
BEGIN
    SELECT a.canonical_id,d.document_type,d.amendment_number INTO earlier
      FROM core.canonical_assertions a JOIN core.requirement_reviews r USING(review_event_id)
      JOIN core.requirement_candidates c USING(candidate_id)
      JOIN core.response_pages p ON p.response_id=c.response_id AND p.page_role='target'
      JOIN core.documents d USING(document_id) WHERE a.assertion_id=NEW.earlier_assertion_id;
    SELECT a.canonical_id,d.document_type,d.amendment_number INTO later
      FROM core.canonical_assertions a JOIN core.requirement_reviews r USING(review_event_id)
      JOIN core.requirement_candidates c USING(candidate_id)
      JOIN core.response_pages p ON p.response_id=c.response_id AND p.page_role='target'
      JOIN core.documents d USING(document_id) WHERE a.assertion_id=NEW.later_assertion_id;
    IF earlier.canonical_id IS NULL OR later.canonical_id IS DISTINCT FROM earlier.canonical_id THEN
        RAISE EXCEPTION 'Amendment endpoints must belong to the same canonical group';
    END IF;
    IF later.document_type <> 'addendum' OR earlier.document_type NOT IN ('original','addendum')
       OR later.amendment_number <= COALESCE(earlier.amendment_number,0) THEN
        RAISE EXCEPTION 'Amendment direction must follow original-to-addendum or increasing addendum numbers';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER validate_amendment_relation BEFORE INSERT ON core.amendment_relations
FOR EACH ROW EXECUTE FUNCTION core.validate_amendment_relation();

CREATE TABLE core.amendment_relation_reviews (
    review_id TEXT PRIMARY KEY,
    relation_id TEXT NOT NULL REFERENCES core.amendment_relations(relation_id),
    decision TEXT NOT NULL CHECK (decision IN ('confirmed','rejected','needs_followup')),
    reviewer TEXT NOT NULL CHECK (length(btrim(reviewer)) > 0),
    review_method TEXT NOT NULL CHECK (review_method IN ('human','assistant','automated')),
    reviewed_at TIMESTAMPTZ NOT NULL,
    recorded_order BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    notes TEXT NOT NULL CHECK (length(btrim(notes)) > 0),
    CHECK (decision <> 'confirmed' OR review_method='human')
);

CREATE FUNCTION core.reject_canonical_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'Canonical and amendment history is append-only; record a new decision or assertion';
END $$;
CREATE TRIGGER immutable_canonical_groups BEFORE UPDATE OR DELETE ON core.canonical_requirements
FOR EACH ROW EXECUTE FUNCTION core.reject_canonical_mutation();
CREATE TRIGGER immutable_canonical_assertions BEFORE UPDATE OR DELETE ON core.canonical_assertions
FOR EACH ROW EXECUTE FUNCTION core.reject_canonical_mutation();
CREATE TRIGGER immutable_amendment_relations BEFORE UPDATE OR DELETE ON core.amendment_relations
FOR EACH ROW EXECUTE FUNCTION core.reject_canonical_mutation();
CREATE TRIGGER immutable_amendment_reviews BEFORE UPDATE OR DELETE ON core.amendment_relation_reviews
FOR EACH ROW EXECUTE FUNCTION core.reject_canonical_mutation();

CREATE INDEX ON core.canonical_assertions(canonical_id);
CREATE INDEX ON core.amendment_relations(later_assertion_id);
CREATE INDEX ON core.amendment_relation_reviews(relation_id,reviewed_at DESC,recorded_order DESC);

CREATE VIEW reporting.canonical_assertion_status AS
SELECT a.assertion_id,a.canonical_id,g.solicitation_id,g.topic_label,a.review_event_id,
       r.candidate_id,r.approved_payload,c.response_id,p.document_id,p.extraction_run_id,p.page_number,
       e.document_sha256,d.document_type,d.amendment_number,
       (latest.review_event_id=a.review_event_id AND latest.decision='accepted') AS review_is_current
FROM core.canonical_assertions a JOIN core.canonical_requirements g USING(canonical_id)
JOIN core.requirement_reviews r USING(review_event_id)
JOIN core.requirement_candidates c USING(candidate_id)
JOIN core.response_pages p ON p.response_id=c.response_id AND p.page_role='target'
JOIN core.page_extractions e USING(extraction_run_id,document_id,page_number)
JOIN core.documents d USING(document_id)
JOIN LATERAL (
  SELECT review_event_id,decision FROM core.requirement_reviews rr WHERE rr.candidate_id=r.candidate_id
  ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1
) latest ON TRUE;

CREATE VIEW reporting.amendment_relation_status AS
SELECT l.*,COALESCE(latest.decision,'unreviewed') AS review_status,
       latest.reviewer,latest.reviewed_at,
       (a.review_is_current AND b.review_is_current) AS endpoints_current,
       (COALESCE(latest.decision='confirmed',false) AND a.review_is_current AND b.review_is_current) AS usable_reviewed_relation
FROM core.amendment_relations l
JOIN reporting.canonical_assertion_status a ON a.assertion_id=l.earlier_assertion_id
JOIN reporting.canonical_assertion_status b ON b.assertion_id=l.later_assertion_id
LEFT JOIN LATERAL (
  SELECT decision,reviewer,reviewed_at FROM core.amendment_relation_reviews rr WHERE rr.relation_id=l.relation_id
  ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1
) latest ON TRUE;
