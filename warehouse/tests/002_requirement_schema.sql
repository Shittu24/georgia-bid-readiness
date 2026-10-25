-- All synthetic records are rolled back, including on failure.
-- Run with psql -v ON_ERROR_STOP=1 -f this_file.
BEGIN;
DO $$
DECLARE sid TEXT := 'schema-test-' || gen_random_uuid()::text;
        doc TEXT; er TEXT; mr TEXT; resp TEXT; bad TEXT; cand TEXT;
        checks INTEGER := 0;
BEGIN
    doc := sid || '-doc'; er := sid || '-extract'; mr := sid || '-model';
    resp := sid || '-response'; bad := sid || '-invalid'; cand := sid || '-candidate';
    INSERT INTO core.solicitations VALUES (sid, sid, sid, 'Synthetic fixture', 'https://example.test', CURRENT_TIMESTAMP);
    INSERT INTO core.documents(document_id,solicitation_id,document_type) VALUES(doc,sid,'original');
    INSERT INTO core.document_versions(document_id,sha256,local_path,size_bytes,page_count)
      VALUES(doc,repeat('a',64),'synthetic.pdf',1,1);
    INSERT INTO core.pipeline_runs(run_id,run_type,status,artifact_path)
      VALUES(er,'extraction','ok','synthetic.json');
    INSERT INTO core.page_extractions(extraction_run_id,document_id,document_sha256,page_number,
      extraction_method,extractor_version,status,raw_text,clean_text,needs_review)
      VALUES(er,doc,repeat('a',64),1,'fixture','1','ok','Sign the proposal.','Sign the proposal.',false);
    INSERT INTO core.model_runs(model_run_id,model_id,model_revision,prompt_version,approach,
      config_sha256,configuration,artifact_path)
      VALUES(mr,'fixture','revision','v1','zero_shot',repeat('b',64),'{}','config.json');
    INSERT INTO core.model_responses(response_id,model_run_id,split,status,raw_response,
      parsed_response,json_valid,schema_valid,output_budget_reached,artifact_path,artifact_sha256)
      VALUES(resp,mr,'development','completed','[]','[]',true,true,false,'result.json',repeat('c',64)),
      (bad,mr,'development','completed','broken',NULL,false,false,true,'bad.json',repeat('d',64));
    checks := checks + 1; -- Invalid output retained as an artifact.
    INSERT INTO core.response_pages VALUES(resp,1,'target',er,doc,1,repeat('e',64));
    INSERT INTO core.requirement_candidates(candidate_id,response_id,output_index,requirement_text,original_prediction)
      VALUES(cand,resp,1,'Sign the proposal.','{"requirement":"Sign the proposal."}');
    BEGIN
      INSERT INTO core.requirement_candidates(candidate_id,response_id,output_index,requirement_text,original_prediction)
        VALUES(cand||'-bad',bad,1,'Bad candidate','{}');
      RAISE EXCEPTION 'FAIL: candidate accepted from invalid response';
    EXCEPTION WHEN foreign_key_violation THEN checks := checks + 1; END;
    BEGIN
      INSERT INTO core.response_pages VALUES(resp,2,'context',er,doc,99,repeat('e',64));
      RAISE EXCEPTION 'FAIL: nonexistent source page accepted';
    EXCEPTION WHEN foreign_key_violation THEN checks := checks + 1; END;
    BEGIN
      INSERT INTO core.requirement_candidates(candidate_id,response_id,output_index,requirement_text,original_prediction)
        VALUES(cand||'-dup',resp,1,'Duplicate position','{}');
      RAISE EXCEPTION 'FAIL: duplicate output position accepted';
    EXCEPTION WHEN unique_violation THEN checks := checks + 1; END;
    INSERT INTO core.requirement_evidence VALUES(cand,resp,1,1,'Sign the proposal.',1,true,'');
    checks := checks + 1;
    BEGIN
      INSERT INTO core.requirement_evidence VALUES(cand,resp,2,1,'Invented quote',1,true,'');
      RAISE EXCEPTION 'FAIL: invented quote marked exact';
    EXCEPTION WHEN raise_exception THEN
      IF SQLERRM <> 'Evidence exact-match flag disagrees with source' THEN RAISE; END IF;
      checks := checks + 1;
    END;
    INSERT INTO core.requirement_evidence VALUES(cand,resp,2,99,'Invented quote',NULL,false,'Unmapped claim');
    checks := checks + 1; -- Bad citations are preserved, not erased.
    BEGIN
      INSERT INTO core.requirement_reviews(review_event_id,candidate_id,decision,reviewer,review_method,reviewed_at,approved_payload,notes)
        VALUES(sid||'-auto',cand,'accepted','model','automated',CURRENT_TIMESTAMP,'{"requirement":"Sign"}','');
      RAISE EXCEPTION 'FAIL: automated approval accepted';
    EXCEPTION WHEN check_violation THEN checks := checks + 1; END;
    INSERT INTO core.requirement_reviews(review_event_id,candidate_id,decision,reviewer,review_method,reviewed_at,approved_payload,notes)
      VALUES(sid||'-review',cand,'accepted','test-human','human',CURRENT_TIMESTAMP,'{"requirement":"Sign the proposal."}','Synthetic review');
    BEGIN
      UPDATE core.requirement_reviews SET notes='rewritten' WHERE review_event_id=sid||'-review';
      RAISE EXCEPTION 'FAIL: review history modified';
    EXCEPTION WHEN raise_exception THEN
      IF SQLERRM <> 'Review history is append-only; insert a new review event' THEN RAISE; END IF;
      checks := checks + 1;
    END;
    INSERT INTO core.requirement_reviews(review_event_id,candidate_id,decision,reviewer,review_method,reviewed_at,notes)
      VALUES(sid||'-followup',cand,'needs_followup','test-human','human',CURRENT_TIMESTAMP + interval '1 second','Reopened');
    IF (SELECT review_status FROM reporting.requirement_review_queue WHERE candidate_id=cand) <> 'needs_followup' THEN
       RAISE EXCEPTION 'FAIL: latest review not reflected';
    END IF;
    checks := checks + 1;
    RAISE NOTICE 'PASS: % requirement-schema checks; synthetic rows will be rolled back', checks;
END $$;
ROLLBACK;
