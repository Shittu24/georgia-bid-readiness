"""Atomic, append-only import of explicitly approved review packages."""
from pathlib import Path
from datetime import datetime
from collections import Counter
import importlib.util
import json
import hashlib
import psycopg
from psycopg.types.json import Jsonb

spec = importlib.util.spec_from_file_location('requirement_loader', Path(__file__).with_name('requirement_loader.py'))
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(path):
    path=Path(path)
    raw=path.read_bytes()
    require(sha(raw)==path.with_suffix('.sha256').read_text().strip(), 'Decision package checksum mismatch')
    package=json.loads(raw)
    require(package['format_version']==1, 'Unsupported review format')
    approval=package['approval']
    require(approval['status']=='approved' and approval['reviewer'].strip(), 'Explicit human approval required')
    require(approval['method']=='assistant_aided_human_approval', 'Unexpected approval method')
    require(approval['authorization_quote'].strip(), 'Approval evidence missing')
    when=datetime.fromisoformat(approval['recorded_at'])
    require(when.tzinfo is not None, 'Approval recording time must include timezone')
    source_raw=(path.parent/'source_packet.json').read_bytes()
    require(sha(source_raw)==package['source_packet_sha256'], 'Source packet checksum mismatch')
    source=json.loads(source_raw)
    by_id={c['candidate_id']:c for c in source['candidates']}
    ids=[r['candidate_id'] for r in package['decisions']]
    require(len(ids)==len(set(ids)) and set(ids)==set(by_id), 'Duplicate or incomplete decision coverage')
    counts=Counter()
    for decision in package['decisions']:
        require(decision['decision'] in ('accepted','rejected','needs_followup'), 'Invalid decision')
        require(decision['rationale'].strip(), 'Review rationale missing')
        if decision['decision']=='accepted':
            payload=decision['approved_payload']
            require(isinstance(payload,dict) and set(payload)=={'requirement','condition','deadline_text','evidence'}, 'Invalid approved payload fields')
            require(isinstance(payload['requirement'],str) and payload['requirement'].strip(), 'Empty reviewed requirement')
            for name in ('condition','deadline_text'):
                require(payload[name] is None or isinstance(payload[name],str), 'Invalid optional text')
            require(isinstance(payload['evidence'],list) and payload['evidence'], 'Reviewed evidence required')
            for e in payload['evidence']:
                require(isinstance(e,dict) and set(e)=={'page_number','quote'}, 'Invalid evidence fields')
                require(type(e['page_number']) is int and e['page_number']>0 and isinstance(e['quote'],str) and e['quote'].strip(), 'Invalid evidence claim')
        else:
            require(decision['approved_payload'] is None, 'Nonaccepted review cannot carry approved payload')
        counts[decision['decision']]+=1
    require(dict(counts)==package['expected_counts'], 'Decision counts disagree')
    return dict(package=package,source=by_id,sha256=sha(raw),recorded_at=when)


def import_reviews(conn, prepared, *, commit=False):
    p=prepared['package'];approval=p['approval'];counts=Counter()
    with conn.transaction():
        with conn.cursor() as cur:
            # Block concurrent review inserts while checking expected prior state.
            # This is a short, local batch transaction, not a long human-review session.
            cur.execute('LOCK TABLE core.requirement_reviews IN SHARE ROW EXCLUSIVE MODE')
            for decision in sorted(p['decisions'],key=lambda x:x['candidate_id']):
                cid=decision['candidate_id'];source=prepared['source'][cid]
                cur.execute('''SELECT c.original_prediction,m.artifact_sha256,c.response_id
                    FROM core.requirement_candidates c JOIN core.model_responses m USING(response_id)
                    WHERE c.candidate_id=%s FOR SHARE OF c,m''',(cid,))
                row=cur.fetchone()
                require(row is not None, f'Missing candidate: {cid}')
                original,artifact_hash,response_id=row
                require(original==source['original_prediction'] and artifact_hash==source['artifact_sha256'], f'Candidate provenance mismatch: {cid}')
                cur.execute('''SELECT p.input_position,p.page_role,p.extraction_run_id,p.document_id,p.page_number,
                    p.text_sha256,e.document_sha256,e.clean_text FROM core.response_pages p
                    JOIN core.page_extractions e USING(extraction_run_id,document_id,page_number)
                    WHERE p.response_id=%s ORDER BY p.input_position FOR SHARE OF p,e''',(response_id,))
                rows=cur.fetchall()
                expected=sorted(source['source_pages'],key=lambda x:x['input_position'])
                require(len(rows)==len(expected), 'Source page count changed')
                for row,expected_page in zip(rows,expected):
                    expected_row=tuple(expected_page[k] for k in ('input_position','page_role','extraction_run_id','document_id','page_number','text_sha256','document_sha256','clean_text'))
                    require(row==expected_row, f'Source provenance/text mismatch: {cid}')
                    require(sha(row[7].strip().encode())==row[5], 'Source text hash mismatch')
                if decision['decision']=='accepted':
                    target_cited=False
                    for claim in decision['approved_payload']['evidence']:
                        matches=[r for r in rows if r[4]==claim['page_number'] and claim['quote'] in r[7]]
                        require(len(matches)==1, f'Reviewed quote does not match claimed page: {cid}')
                        target_cited=target_cited or matches[0][1]=='target'
                    require(target_cited, 'Accepted obligation needs target-page evidence')
                event='review-'+sha((p['batch_id']+'\0'+cid).encode())
                notes=json.dumps(dict(batch_id=p['batch_id'],decision_package_sha256=prepared['sha256'],
                    source_packet_sha256=p['source_packet_sha256'],review_process=approval['method'],
                    authorization_quote=approval['authorization_quote'],authorization_source=approval['source'],
                    timestamp_note=approval['timestamp_note'],rationale=decision['rationale']),sort_keys=True,ensure_ascii=False)
                values=dict(review_event_id=event,candidate_id=cid,decision=decision['decision'],
                    reviewer=approval['reviewer'],review_method='human',reviewed_at=prepared['recorded_at'],
                    approved_payload=decision['approved_payload'],notes=notes)
                cur.execute('SELECT 1 FROM core.requirement_reviews WHERE review_event_id=%s',(event,))
                exists=cur.fetchone() is not None
                cur.execute('''SELECT review_event_id,reviewed_at FROM core.requirement_reviews WHERE candidate_id=%s
                    ORDER BY reviewed_at DESC,recorded_order DESC LIMIT 1''',(cid,))
                latest=cur.fetchone()
                if not exists:
                    require((latest[0] if latest else None)==decision['expected_prior_review_event_id'], f'Review state changed: {cid}')
                    require(latest is None or prepared['recorded_at']>=latest[1], 'New review would be chronologically stale')
                inserted=base.insert_or_verify(cur,'requirement_reviews',['review_event_id'],values)
                counts['reviews_inserted' if inserted else 'reviews_reused']+=1
                counts[decision['decision']]+=1
                if exists and latest and latest[0]!=event:
                    counts['historical_reviews_reused']+=1
            if not commit:
                raise psycopg.Rollback()
    return dict(mode='committed' if commit else 'preview_rolled_back',counts=dict(counts),
                batch_id=p['batch_id'],decision_package_sha256=prepared['sha256'])
