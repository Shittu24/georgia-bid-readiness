import sys,copy,uuid,importlib.util,json
from pathlib import Path
import pytest
import psycopg
from psycopg.types.json import Jsonb
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from complete_reviewed_requirements import populate
from de_backup import fingerprints
from run_de_pipeline import execute
spec=importlib.util.spec_from_file_location('base_de_tests',ROOT/'tests/test_requirement_loader.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
bundle=base.bundle;db=base.db

@pytest.fixture
def setup(db):
 conn,prepared=db;base.loader.load(conn,prepared,commit=True)
 ids=[r['response_id'] for r in prepared['responses']]
 rows=conn.execute('SELECT candidate_id FROM core.requirement_candidates WHERE response_id=ANY(%s) ORDER BY candidate_id',(ids,)).fetchall()
 members=[];payload=dict(requirement='Sign the proposal.',condition=None,deadline_text=None,evidence=[dict(page_number=1,quote='Sign the proposal.')])
 for (cid,) in rows:
  rid=uuid.uuid4().hex
  conn.execute("INSERT INTO core.requirement_reviews(review_event_id,candidate_id,decision,reviewer,review_method,reviewed_at,approved_payload,notes) VALUES(%s,%s,'accepted','Test human','human',clock_timestamp(),%s,'Fixture approval')",(rid,cid,Jsonb(payload)))
  members.append(dict(candidate_id=cid,review_event_id=rid,approved_payload=payload))
 p=dict(grouping_authorized_by='Test human',groups=[dict(canonical_id='fixture-'+uuid.uuid4().hex,label='Sign',members=members)],split_drafts=[])
 return conn,p,payload

def test_group_preview_no_rows(setup):
 c,p,_=setup;result=populate(c,p)
 assert result['counts']['groups_inserted']==1
 assert c.execute('SELECT count(*) FROM core.canonical_requirements WHERE canonical_id=%s',(p['groups'][0]['canonical_id'],)).fetchone()[0]==0

def test_group_repeat_preserves_sources(setup):
 c,p,_=setup;a=populate(c,p,True);b=populate(c,p,True)
 assert a['counts']['assertions_inserted']==2 and b['counts']['assertions_reused']==2
 assert b['counts']['groups_reused']==1

def test_changed_approved_payload_blocks_grouping(setup):
 c,p,_=setup;q=copy.deepcopy(p);q['groups'][0]['members'][0]['approved_payload']['requirement']='Changed'
 with pytest.raises(ValueError,match='review changed'):populate(c,q,True)

def split_plan(c,p,payload):
 ids=[m['candidate_id'] for m in p['groups'][0]['members']]
 for cid in ids:
  c.execute("INSERT INTO core.requirement_reviews(review_event_id,candidate_id,decision,reviewer,review_method,reviewed_at,notes) VALUES(%s,%s,'needs_followup','Test human','human',clock_timestamp(),'Split needed')",(uuid.uuid4().hex,cid))
 return dict(grouping_authorized_by='Test human',groups=[],split_drafts=[dict(split_id='fixture-'+uuid.uuid4().hex,origin_candidate_ids=ids,payload=payload)])

def test_split_drafts_remain_unreviewed_and_repeat_safe(setup):
 c,p,payload=setup;q=split_plan(c,p,payload);a=populate(c,q,True);b=populate(c,q,True)
 assert a['counts']['split_drafts_inserted']==1 and a['counts']['split_origins_inserted']==2
 assert b['counts']['split_drafts_reused']==1
 assert c.execute('SELECT review_status FROM reporting.split_requirement_status WHERE split_id=%s',(q['split_drafts'][0]['split_id'],)).fetchone()[0]=='unreviewed'

def test_wrong_split_evidence_rolls_back(setup):
 c,p,payload=setup;bad=copy.deepcopy(payload);bad['evidence'][0]['quote']='Invented';q=split_plan(c,p,bad)
 with pytest.raises(psycopg.errors.RaiseException,match='does not match'):populate(c,q,True)
 assert c.execute('SELECT count(*) FROM core.split_requirements WHERE split_id=%s',(q['split_drafts'][0]['split_id'],)).fetchone()[0]==0

def test_fingerprints_detect_content_change_with_same_count(setup):
 c,p,_=setup;a=fingerprints(c)
 cid=p['groups'][0]['members'][0]['candidate_id']
 c.execute("UPDATE core.requirement_candidates SET requirement_text='Test mutation' WHERE candidate_id=%s",(cid,))
 b=fingerprints(c)
 assert a['core.requirement_candidates']['rows']==b['core.requirement_candidates']['rows']
 assert a['core.requirement_candidates']['sha256']!=b['core.requirement_candidates']['sha256']

def test_failed_stage_stops_and_keeps_log(tmp_path):
 log=tmp_path/'failure.log'
 with pytest.raises(RuntimeError,match='Stage failed'):execute([sys.executable,'-c',"print('intentional failure');raise SystemExit(3)"],log)
 assert 'intentional failure' in log.read_text()
