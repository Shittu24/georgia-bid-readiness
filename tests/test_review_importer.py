import importlib.util,json,copy,uuid
from pathlib import Path
from datetime import datetime,timezone
import pytest
import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
base=module('base_reviews_test',ROOT/'tests/test_requirement_loader.py')
review=module('review_importer',ROOT/'src/transformation/review_importer.py')
bundle=base.bundle
db=base.db

def save(path,package):
    raw=json.dumps(package).encode();path.write_bytes(raw);path.with_suffix('.sha256').write_text(review.sha(raw))

@pytest.fixture
def fixture(db,tmp_path):
    conn,p=db;base.loader.load(conn,p,commit=True)
    ids=[r['response_id'] for r in p['responses']]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT c.*,m.artifact_sha256 FROM core.requirement_candidates c JOIN core.model_responses m USING(response_id) WHERE c.response_id=ANY(%s) ORDER BY candidate_id',(ids,))
        candidates=cur.fetchall()
        for c in candidates:
            cur.execute('SELECT p.*,e.document_sha256,e.clean_text FROM core.response_pages p JOIN core.page_extractions e USING(extraction_run_id,document_id,page_number) WHERE p.response_id=%s ORDER BY input_position',(c['response_id'],));c['source_pages']=cur.fetchall()
    raw=json.dumps(dict(candidates=candidates)).encode();(tmp_path/'source_packet.json').write_bytes(raw)
    package=dict(format_version=1,batch_id=uuid.uuid4().hex,source_packet_sha256=review.sha(raw),
        approval=dict(status='approved',reviewer='Synthetic human',method='assistant_aided_human_approval',authorization_quote='Synthetic test approval',source='Test fixture',recorded_at=datetime.now(timezone.utc).isoformat(),timestamp_note='Synthetic time'),expected_counts=dict(accepted=1,rejected=1),decisions=[])
    for i,c in enumerate(candidates):
        payload=dict(requirement='Sign the proposal.',condition=None,deadline_text=None,evidence=[dict(page_number=1,quote='Sign the proposal.')]) if i==0 else None
        package['decisions'].append(dict(candidate_id=c['candidate_id'],decision='accepted' if i==0 else 'rejected',approved_payload=payload,rationale='Synthetic decision',expected_prior_review_event_id=None))
    path=tmp_path/'approved_decisions.json';save(path,package)
    return conn,path

def count(conn,prepared):
    ids=[d['candidate_id'] for d in prepared['package']['decisions']]
    return conn.execute('SELECT count(*) FROM core.requirement_reviews WHERE candidate_id=ANY(%s)',(ids,)).fetchone()[0]

def test_review_preview_rolls_back(fixture):
    conn,path=fixture;p=review.prepare(path)
    assert review.import_reviews(conn,p)['mode']=='preview_rolled_back'
    assert count(conn,p)==0

def test_review_commit_repeat(fixture):
    conn,path=fixture;p=review.prepare(path)
    assert review.import_reviews(conn,p,commit=True)['counts']['reviews_inserted']==2
    assert review.import_reviews(conn,p,commit=True)['counts']['reviews_reused']==2
    assert count(conn,p)==2

def test_modified_package_checksum(fixture):
    _,path=fixture;path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='checksum'):review.prepare(path)

def test_missing_human_approval(fixture):
    _,path=fixture;p=json.loads(path.read_bytes());p['approval']['status']='draft';save(path,p)
    with pytest.raises(ValueError,match='approval'):review.prepare(path)

def test_duplicate_decision(fixture):
    _,path=fixture;p=json.loads(path.read_bytes());p['decisions'].append(p['decisions'][0]);save(path,p)
    with pytest.raises(ValueError,match='coverage'):review.prepare(path)

def test_wrong_reviewed_quote_rolls_back(fixture):
    conn,path=fixture;p=review.prepare(path)
    p['package']['decisions'][0]['approved_payload']['evidence'][0]['quote']='Not in source'
    with pytest.raises(ValueError,match='quote'):review.import_reviews(conn,p,commit=True)
    assert count(conn,p)==0

def test_changed_source_rolls_back(fixture):
    conn,path=fixture;p=review.prepare(path);first=p['package']['decisions'][0]['candidate_id']
    p['source'][first]['source_pages'][0]['document_sha256']='b'*64
    with pytest.raises(ValueError,match='provenance'):review.import_reviews(conn,p,commit=True)
    assert count(conn,p)==0

def test_existing_review_stops_new_batch(fixture):
    conn,path=fixture;p=review.prepare(path);cid=sorted(d['candidate_id'] for d in p['package']['decisions'])[-1]
    conn.execute("INSERT INTO core.requirement_reviews(review_event_id,candidate_id,decision,reviewer,review_method,reviewed_at,notes) VALUES(%s,%s,'needs_followup','other','human',clock_timestamp(),'New review')",(uuid.uuid4().hex,cid))
    with pytest.raises(ValueError,match='state changed'):review.import_reviews(conn,p,commit=True)
    assert count(conn,p)==1

def test_changed_reimport_rejected(fixture):
    conn,path=fixture;p=review.prepare(path);review.import_reviews(conn,p,commit=True)
    p['package']['decisions'][-1]['rationale']='Changed decision rationale'
    with pytest.raises(ValueError,match='Conflicting existing'):review.import_reviews(conn,p,commit=True)
    assert count(conn,p)==2

def test_historical_repeat_does_not_override_new_review(fixture):
    conn,path=fixture;p=review.prepare(path);review.import_reviews(conn,p,commit=True)
    cid=p['package']['decisions'][0]['candidate_id']
    new=uuid.uuid4().hex
    conn.execute("INSERT INTO core.requirement_reviews(review_event_id,candidate_id,decision,reviewer,review_method,reviewed_at,notes) VALUES(%s,%s,'needs_followup','other','human',clock_timestamp(),'Reopened')",(new,cid))
    result=review.import_reviews(conn,p,commit=True)
    assert result['counts']['historical_reviews_reused']==1
    assert count(conn,p)==3
