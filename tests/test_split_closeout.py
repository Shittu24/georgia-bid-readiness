import copy,sys,uuid,importlib.util
from pathlib import Path
from datetime import datetime,timezone,timedelta
import psycopg,pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from closeout_split_requirements import apply
from complete_reviewed_requirements import populate
spec=importlib.util.spec_from_file_location('de_fixtures',ROOT/'tests/test_de_completion.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
bundle=base.bundle;db=base.db;setup=base.setup

@pytest.fixture
def closeout(setup):
 c,p,payload=setup
 splitplan=base.split_plan(c,p,payload)
 first=splitplan['split_drafts'][0]
 splitplan['split_drafts']=[dict(first,split_id='split-test-'+uuid.uuid4().hex) for _ in range(4)]
 populate(c,splitplan,True)
 parents={}
 for cid in first['origin_candidate_ids']:
  latest=c.execute('SELECT review_event_id FROM core.requirement_reviews WHERE candidate_id=%s ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1',(cid,)).fetchone()[0]
  sources=c.execute('''SELECT p.extraction_run_id,p.document_id,p.page_number,p.page_role,p.text_sha256,e.document_sha256,e.clean_text
  FROM core.requirement_candidates c JOIN core.response_pages p USING(response_id)
  JOIN core.page_extractions e USING(extraction_run_id,document_id,page_number) WHERE c.candidate_id=%s ORDER BY p.input_position''',(cid,)).fetchall()
  parents[cid]=dict(review_event_id=latest,sources=[list(x) for x in sources])
 sid=c.execute('SELECT solicitation_id FROM reporting.split_requirement_status WHERE split_id=%s',(splitplan['split_drafts'][0]['split_id'],)).fetchone()[0]
 package=dict(human_approval='Approve all four',reviewer='Test human',reviewed_at=datetime.now(timezone.utc).isoformat(),solicitation_id=sid,splits=splitplan['split_drafts'],parents=parents)
 return c,package

def test_closeout_preview_rolls_back(closeout):
 c,p=closeout;result=apply(c,p)
 assert result['counts']['split_requirement_reviews_inserted']==4
 assert c.execute('SELECT count(*) FROM core.split_requirement_reviews WHERE split_id=ANY(%s)',([d['split_id'] for d in p['splits']],)).fetchone()[0]==0

def test_closeout_repeat_and_no_parent_double_count(closeout):
 c,p=closeout;apply(c,p,True);r=apply(c,p,True)
 assert r['counts']['canonical_split_assertions_reused']==4
 rows=c.execute('SELECT resolved_by_split FROM reporting.split_parent_resolution WHERE candidate_id=ANY(%s)',(list(p['parents']),)).fetchall()
 assert rows and all(x[0] for x in rows)
 assert c.execute('SELECT count(*) FROM reporting.current_requirement_assertions WHERE solicitation_id=%s',(p['solicitation_id'],)).fetchone()[0]==4

def test_closeout_changed_draft_rejected(closeout):
 c,p=closeout;p=copy.deepcopy(p);p['splits'][0]['payload']['requirement']='Invented'
 with pytest.raises(ValueError,match='draft changed'):apply(c,p,True)

def test_closeout_changed_source_rejected(closeout):
 c,p=closeout;p=copy.deepcopy(p);next(iter(p['parents'].values()))['sources'][0][-1]='Changed'
 with pytest.raises(ValueError,match='provenance changed'):apply(c,p,True)

def test_closeout_requires_explicit_approval(closeout):
 c,p=closeout;p['human_approval']='pending'
 with pytest.raises(ValueError,match='approval missing'):apply(c,p,True)

def test_closeout_late_conflict_rolls_back_batch(closeout):
 c,p=closeout;p=copy.deepcopy(p);p['splits'][-1]['payload']['requirement']='Changed last draft'
 with pytest.raises(ValueError):apply(c,p,True)
 assert c.execute('SELECT count(*) FROM core.split_requirement_reviews WHERE split_id=ANY(%s)',([d['split_id'] for d in p['splits']],)).fetchone()[0]==0

def test_closeout_reopened_review_disables_resolution(closeout):
 c,p=closeout;apply(c,p,True)
 c.execute("INSERT INTO core.split_requirement_reviews(review_id,split_id,decision,reviewer,review_method,reviewed_at,notes) VALUES(%s,%s,'needs_followup','Test human','human',%s,'Reopen')",(uuid.uuid4().hex,p['splits'][0]['split_id'],datetime.now(timezone.utc)+timedelta(seconds=2)))
 rows=c.execute('SELECT resolved_by_split FROM reporting.split_parent_resolution WHERE candidate_id=ANY(%s)',(list(p['parents']),)).fetchall()
 assert not any(r[0] for r in rows)
 with pytest.raises(ValueError,match='different review'):apply(c,p,True)

def test_closeout_assertion_history_immutable(closeout):
 c,p=closeout;apply(c,p,True)
 with pytest.raises(psycopg.errors.RaiseException,match='append-only'):
  with c.transaction():c.execute('DELETE FROM core.canonical_split_assertions WHERE assertion_id=%s',('assert-'+p['splits'][0]['split_id'],))
