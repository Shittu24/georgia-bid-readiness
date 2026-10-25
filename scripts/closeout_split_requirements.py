"""Import the four explicitly human-approved splits with immutable lineage."""
from pathlib import Path
import argparse,hashlib,json
from datetime import datetime
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from de_common import ROOT,settings,require

def read_package():
 p=ROOT/'configs/split_closeout_approval.json';raw=p.read_bytes()
 require(hashlib.sha256(raw).hexdigest()==p.with_suffix('.sha256').read_text().strip(),'Approval package checksum mismatch')
 package=json.loads(raw)
 require(package['human_approval']=='Approve all four','Explicit approval missing')
 return package

def apply(conn,p,commit=False):
 require(p.get('human_approval')=='Approve all four','Explicit approval missing')
 require(len(p['splits'])==4 and len({d['split_id'] for d in p['splits']})==4,'Expected four distinct splits')
 counts={}
 with conn.transaction():
  conn.execute('SELECT pg_advisory_xact_lock(7050,90)')
  conn.execute('LOCK TABLE core.split_requirement_reviews,core.requirement_reviews,core.split_requirement_origins IN SHARE ROW EXCLUSIVE MODE')
  def put(table,key,record):
   columns=list(record);values=[Jsonb(v) if isinstance(v,(dict,list)) else v for v in record.values()]
   old=conn.execute(sql.SQL('SELECT {} FROM core.{} WHERE {}=%s').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table),sql.Identifier(key)),(record[key],)).fetchone()
   if old:
    expected=[datetime.fromisoformat(v) if isinstance(actual,datetime) else v for actual,v in zip(old,record.values())]
    require(list(old)==expected,f'Conflicting existing {table} record')
    counts[table+'_reused']=counts.get(table+'_reused',0)+1
   else:
    conn.execute(sql.SQL('INSERT INTO core.{} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns)),values)
    counts[table+'_inserted']=counts.get(table+'_inserted',0)+1
  for draft in p['splits']:
   sid=draft['split_id']
   row=conn.execute('SELECT proposed_payload FROM core.split_requirements WHERE split_id=%s',(sid,)).fetchone()
   require(row and row[0]==draft['payload'],'Split draft changed or missing')
   origins=[r[0] for r in conn.execute('SELECT candidate_id FROM core.split_requirement_origins WHERE split_id=%s ORDER BY candidate_id',(sid,))]
   require(origins==sorted(draft['origin_candidate_ids']),'Split origins changed')
   for cid in origins:
    latest=conn.execute('SELECT review_event_id,decision FROM core.requirement_reviews WHERE candidate_id=%s ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1',(cid,)).fetchone()
    require(latest==(p['parents'][cid]['review_event_id'],'needs_followup'),'Parent review changed')
    source=conn.execute('''SELECT p.extraction_run_id,p.document_id,p.page_number,p.page_role,p.text_sha256,e.document_sha256,e.clean_text
      FROM core.requirement_candidates c JOIN core.response_pages p USING(response_id)
      JOIN core.page_extractions e USING(extraction_run_id,document_id,page_number)
      WHERE c.candidate_id=%s ORDER BY p.input_position''',(cid,)).fetchall()
    expected=p['parents'][cid]['sources']
    require([list(r) for r in source]==expected,'Parent source provenance changed')
   review_id='split-approval-v1-'+sid
   latest=conn.execute('SELECT review_id,decision FROM core.split_requirement_reviews WHERE split_id=%s ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1',(sid,)).fetchone()
   require(latest is None or latest==(review_id,'accepted'),'Split already has a different review; no historical overwrite')
   put('split_requirement_reviews','review_id',dict(review_id=review_id,split_id=sid,decision='accepted',reviewer=p['reviewer'],review_method='human',reviewed_at=p['reviewed_at'],notes='Explicit user approval: Approve all four. Evidence and source lineage rechecked at import.'))
   canonical='approved-'+sid
   put('canonical_requirements','canonical_id',dict(canonical_id=canonical,solicitation_id=p['solicitation_id'],topic_label=draft['payload']['requirement'],created_by=p['reviewer']))
   put('canonical_split_assertions','assertion_id',dict(assertion_id='assert-'+sid,canonical_id=canonical,split_review_id=review_id,linked_by=p['reviewer']))
  if not commit:raise psycopg.Rollback()
 return dict(mode='committed' if commit else 'preview_rolled_back',counts=counts)

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--commit',action='store_true');args=ap.parse_args()
 with psycopg.connect(**settings(),autocommit=True) as conn:
  print(json.dumps(apply(conn,read_package(),args.commit),indent=2))
