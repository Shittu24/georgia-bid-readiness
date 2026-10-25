-- Preserve proposed split obligations separately from raw predictions and reviews.
CREATE TABLE core.split_requirements (
 split_id TEXT PRIMARY KEY,
 anchor_candidate_id TEXT NOT NULL REFERENCES core.requirement_candidates(candidate_id),
 proposed_payload JSONB NOT NULL CHECK(jsonb_typeof(proposed_payload)='object'),
 proposed_by TEXT NOT NULL,
 rationale TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE core.split_requirement_origins (
 split_id TEXT NOT NULL REFERENCES core.split_requirements(split_id),
 candidate_id TEXT NOT NULL REFERENCES core.requirement_candidates(candidate_id),
 PRIMARY KEY(split_id,candidate_id)
);
CREATE TABLE core.split_requirement_reviews (
 review_id TEXT PRIMARY KEY,
 split_id TEXT NOT NULL REFERENCES core.split_requirements(split_id),
 decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected','needs_followup')),
 reviewer TEXT NOT NULL CHECK(length(btrim(reviewer))>0),
 review_method TEXT NOT NULL CHECK(review_method IN ('human','assistant','automated')),
 reviewed_at TIMESTAMPTZ NOT NULL,
 recorded_order BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
 notes TEXT NOT NULL,
 CHECK(decision<>'accepted' OR review_method='human')
);
CREATE FUNCTION core.validate_split_requirement() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r TEXT; target_page INTEGER; e JSONB; matched BOOLEAN; target_cited BOOLEAN:=false;
BEGIN
 SELECT c.response_id,p.page_number INTO r,target_page FROM core.requirement_candidates c
 JOIN core.response_pages p ON p.response_id=c.response_id AND p.page_role='target'
 WHERE c.candidate_id=NEW.anchor_candidate_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Split anchor must have a target source'; END IF;
 IF jsonb_typeof(NEW.proposed_payload->'requirement') IS DISTINCT FROM 'string'
 OR COALESCE(length(btrim(NEW.proposed_payload->>'requirement')),0)=0
 OR jsonb_typeof(NEW.proposed_payload->'evidence') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Split payload needs requirement text and evidence';
 END IF;
 FOR e IN SELECT * FROM jsonb_array_elements(NEW.proposed_payload->'evidence') LOOP
  IF jsonb_typeof(e->'quote') IS DISTINCT FROM 'string' OR COALESCE(length(btrim(e->>'quote')),0)=0 THEN
   RAISE EXCEPTION 'Split evidence quote cannot be blank';
  END IF;
  SELECT EXISTS(SELECT 1 FROM core.response_pages p JOIN core.page_extractions x
   USING(extraction_run_id,document_id,page_number)
   WHERE p.response_id=r AND p.page_number::text=e->>'page_number' AND strpos(x.clean_text,e->>'quote')>0) INTO matched;
  IF NOT matched THEN RAISE EXCEPTION 'Split evidence does not match supplied source'; END IF;
  target_cited:=target_cited OR target_page::text=e->>'page_number';
 END LOOP;
 IF NOT target_cited THEN RAISE EXCEPTION 'Split requires target evidence'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validate_split_requirement BEFORE INSERT ON core.split_requirements
 FOR EACH ROW EXECUTE FUNCTION core.validate_split_requirement();
CREATE FUNCTION core.validate_split_origin() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a TEXT; b TEXT;
BEGIN
 SELECT p.document_id INTO a FROM core.split_requirements s JOIN core.requirement_candidates c
 ON c.candidate_id=s.anchor_candidate_id JOIN core.response_pages p ON p.response_id=c.response_id AND p.page_role='target'
 WHERE s.split_id=NEW.split_id;
 SELECT p.document_id INTO b FROM core.requirement_candidates c JOIN core.response_pages p
 ON p.response_id=c.response_id AND p.page_role='target' WHERE c.candidate_id=NEW.candidate_id;
 IF a IS NULL OR b IS DISTINCT FROM a THEN RAISE EXCEPTION 'Split origins must belong to the same source document'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validate_split_origin BEFORE INSERT ON core.split_requirement_origins
 FOR EACH ROW EXECUTE FUNCTION core.validate_split_origin();
CREATE TRIGGER immutable_splits BEFORE UPDATE OR DELETE ON core.split_requirements
 FOR EACH ROW EXECUTE FUNCTION core.reject_canonical_mutation();
CREATE TRIGGER immutable_split_origins BEFORE UPDATE OR DELETE ON core.split_requirement_origins
 FOR EACH ROW EXECUTE FUNCTION core.reject_canonical_mutation();
CREATE TRIGGER immutable_split_reviews BEFORE UPDATE OR DELETE ON core.split_requirement_reviews
 FOR EACH ROW EXECUTE FUNCTION core.reject_canonical_mutation();
CREATE VIEW reporting.split_requirement_status AS
 SELECT s.*,d.solicitation_id,p.document_id,p.page_number,
 COALESCE(r.decision,'unreviewed') AS review_status,r.reviewer,r.reviewed_at
 FROM core.split_requirements s JOIN core.requirement_candidates c ON c.candidate_id=s.anchor_candidate_id
 JOIN core.response_pages p ON p.response_id=c.response_id AND p.page_role='target'
 JOIN core.documents d USING(document_id)
 LEFT JOIN LATERAL(SELECT decision,reviewer,reviewed_at FROM core.split_requirement_reviews rr
 WHERE rr.split_id=s.split_id ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1) r ON true;
