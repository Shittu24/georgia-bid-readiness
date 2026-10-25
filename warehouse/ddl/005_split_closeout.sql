-- Approved split assertions retain their own review lineage; raw candidates stay unchanged.
CREATE TABLE core.canonical_split_assertions (
 assertion_id TEXT PRIMARY KEY,
 canonical_id TEXT NOT NULL REFERENCES core.canonical_requirements(canonical_id),
 split_review_id TEXT NOT NULL UNIQUE REFERENCES core.split_requirement_reviews(review_id),
 linked_by TEXT NOT NULL CHECK(length(btrim(linked_by))>0),
 linked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE FUNCTION core.validate_canonical_split_assertion() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r RECORD; latest TEXT; source_sid TEXT; group_sid TEXT; origin TEXT; claim JSONB;
BEGIN
 SELECT * INTO r FROM core.split_requirement_reviews WHERE review_id=NEW.split_review_id;
 IF NOT FOUND OR r.decision<>'accepted' OR r.review_method<>'human' THEN
  RAISE EXCEPTION 'Split assertion requires accepted human review';
 END IF;
 SELECT review_id INTO latest FROM core.split_requirement_reviews WHERE split_id=r.split_id
 ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1;
 IF latest IS DISTINCT FROM r.review_id THEN RAISE EXCEPTION 'Stale split review'; END IF;
 SELECT solicitation_id INTO source_sid FROM reporting.split_requirement_status WHERE split_id=r.split_id;
 SELECT solicitation_id INTO group_sid FROM core.canonical_requirements WHERE canonical_id=NEW.canonical_id;
 IF source_sid IS DISTINCT FROM group_sid THEN RAISE EXCEPTION 'Cross-solicitation split group'; END IF;
 FOR origin IN SELECT candidate_id FROM core.split_requirement_origins WHERE split_id=r.split_id LOOP
  IF EXISTS(SELECT 1 FROM reporting.canonical_assertion_status WHERE candidate_id=origin AND review_is_current) THEN
   RAISE EXCEPTION 'Combined parent already canonical; would double count';
  END IF;
 END LOOP;
 -- Validate evidence again at promotion, not just when the draft was inserted.
 FOR claim IN SELECT jsonb_array_elements(proposed_payload->'evidence') FROM core.split_requirements WHERE split_id=r.split_id LOOP
  IF NOT EXISTS(SELECT 1 FROM core.split_requirements s JOIN core.requirement_candidates c
   ON c.candidate_id=s.anchor_candidate_id JOIN core.response_pages p ON p.response_id=c.response_id
   JOIN core.page_extractions e USING(extraction_run_id,document_id,page_number)
   WHERE s.split_id=r.split_id AND p.page_number::text=claim->>'page_number'
   AND strpos(e.clean_text,claim->>'quote')>0) THEN RAISE EXCEPTION 'Split source evidence changed'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER validate_canonical_split_assertion BEFORE INSERT ON core.canonical_split_assertions
 FOR EACH ROW EXECUTE FUNCTION core.validate_canonical_split_assertion();
CREATE TRIGGER immutable_canonical_split_assertions BEFORE UPDATE OR DELETE ON core.canonical_split_assertions
 FOR EACH ROW EXECUTE FUNCTION core.reject_canonical_mutation();

CREATE VIEW reporting.canonical_split_assertion_status AS
 SELECT a.*,r.split_id,s.solicitation_id,s.document_id,s.page_number,s.proposed_payload,
 (latest.review_id=r.review_id AND latest.decision='accepted') AS review_is_current
 FROM core.canonical_split_assertions a JOIN core.split_requirement_reviews r ON r.review_id=a.split_review_id
 JOIN reporting.split_requirement_status s USING(split_id)
 JOIN LATERAL(SELECT review_id,decision FROM core.split_requirement_reviews rr WHERE rr.split_id=r.split_id
 ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1) latest ON true;

CREATE VIEW reporting.split_parent_resolution AS
 SELECT o.candidate_id,count(*) split_count,
 bool_and(EXISTS(SELECT 1 FROM reporting.canonical_split_assertion_status a
 WHERE a.split_id=o.split_id AND a.review_is_current)) AS splits_current,
 (SELECT review_status FROM reporting.requirement_review_queue q WHERE q.candidate_id=o.candidate_id) AS parent_review_status,
 (bool_and(EXISTS(SELECT 1 FROM reporting.canonical_split_assertion_status a
 WHERE a.split_id=o.split_id AND a.review_is_current))
 AND (SELECT review_status FROM reporting.requirement_review_queue q WHERE q.candidate_id=o.candidate_id)='needs_followup'
 AND NOT EXISTS(SELECT 1 FROM reporting.canonical_assertion_status c WHERE c.candidate_id=o.candidate_id AND c.review_is_current))
 AS resolved_by_split
 FROM core.split_requirement_origins o GROUP BY o.candidate_id;

CREATE VIEW reporting.current_requirement_assertions AS
 SELECT 'candidate:'||a.assertion_id AS assertion_key,a.canonical_id,a.solicitation_id,
 a.approved_payload AS payload,'candidate_review'::text AS source_type,a.document_id,a.page_number
 FROM reporting.canonical_assertion_status a WHERE a.review_is_current
 -- Split-linked parents are never simultaneously promoted in this unified view.
 AND NOT EXISTS(SELECT 1 FROM core.split_requirement_origins o
 JOIN reporting.canonical_split_assertion_status s USING(split_id)
 WHERE o.candidate_id=a.candidate_id AND s.review_is_current)
 UNION ALL
 SELECT 'split:'||a.assertion_id,a.canonical_id,a.solicitation_id,a.proposed_payload,
 'split_review',a.document_id,a.page_number
 FROM reporting.canonical_split_assertion_status a WHERE a.review_is_current;
