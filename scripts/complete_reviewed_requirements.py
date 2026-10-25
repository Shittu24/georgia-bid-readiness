"""Populate approved groups and unapproved split drafts. Preview is default."""
import argparse,json,hashlib
import psycopg
from de_common import loader,settings,plan,require

def populate(conn,p,commit=False):
 counts={'groups_inserted':0,'groups_reused':0,'assertions_inserted':0,'assertions_reused':0,
         'split_drafts_inserted':0,'split_drafts_reused':0,'split_origins_inserted':0,'split_origins_reused':0}
 with conn.transaction():
  with conn.cursor() as cur:
   cur.execute('LOCK TABLE core.requirement_reviews IN SHARE ROW EXCLUSIVE MODE')
   def put(table,keys,values,label):
    fresh=loader.insert_or_verify(cur,table,keys,values)
    counts[label+('_inserted' if fresh else '_reused')]+=1
   for group in p['groups']:
    members=[];solicitation=None
    for m in group['members']:
     cur.execute('''SELECT r.review_event_id,r.decision,r.approved_payload,d.solicitation_id FROM core.requirement_reviews r
      JOIN core.requirement_candidates c USING(candidate_id)
      JOIN core.response_pages rp ON rp.response_id=c.response_id AND rp.page_role='target'
      JOIN core.documents d USING(document_id) WHERE r.candidate_id=%s
      ORDER BY r.reviewed_at DESC,r.recorded_order DESC LIMIT 1''',(m['candidate_id'],))
     row=cur.fetchone();require(row is not None,'Approved review missing')
     require(row[0]==m['review_event_id'] and row[1]=='accepted' and row[2]==m['approved_payload'],'Approved review changed; regrouping requires review')
     require(solicitation is None or solicitation==row[3],'Group crosses solicitations');solicitation=row[3];members.append(m)
    put('canonical_requirements',['canonical_id'],dict(canonical_id=group['canonical_id'],solicitation_id=solicitation,
        topic_label=group['label'],created_by=p['grouping_authorized_by']),'groups')
    for m in members:
     aid='assert-'+hashlib.sha256((group['canonical_id']+'|'+m['review_event_id']).encode()).hexdigest()
     put('canonical_assertions',['assertion_id'],dict(assertion_id=aid,canonical_id=group['canonical_id'],review_event_id=m['review_event_id'],
       linked_by=p['grouping_authorized_by'],rationale='Approved pilot obligation; grouped by the reviewed DE plan.'),'assertions')
   for draft in p['split_drafts']:
    for cid in draft['origin_candidate_ids']:
     cur.execute('SELECT decision FROM core.requirement_reviews WHERE candidate_id=%s ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1',(cid,))
     row=cur.fetchone();require(row is not None and row[0]=='needs_followup','Split parent review changed; inspect before continuing')
    put('split_requirements',['split_id'],dict(split_id=draft['split_id'],anchor_candidate_id=draft['origin_candidate_ids'][0],
      proposed_payload=draft['payload'],proposed_by='assistant',rationale='Separate signing from returning; draft only. No new human approval inferred.'),'split_drafts')
    for cid in draft['origin_candidate_ids']:
     put('split_requirement_origins',['split_id','candidate_id'],dict(split_id=draft['split_id'],candidate_id=cid),'split_origins')
  if not commit:raise psycopg.Rollback()
 return {'mode':'committed' if commit else 'preview_rolled_back','counts':counts}

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--commit',action='store_true');a=ap.parse_args()
 with psycopg.connect(**settings(),autocommit=True) as conn:print(json.dumps(populate(conn,plan(),a.commit),indent=2))
