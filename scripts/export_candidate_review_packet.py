"""Export unreviewed candidates and source text; never approve or import reviews."""
import importlib.util
from pathlib import Path
from datetime import datetime, timezone
import json
import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('requirement_loader',ROOT/'src/transformation/requirement_loader.py')
loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)


def main():
    with psycopg.connect(**loader.settings(),row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        records=conn.execute("""SELECT q.*,c.original_prediction,m.artifact_path,m.artifact_sha256,
            r.model_id,r.approach FROM reporting.requirement_review_queue q
            JOIN core.requirement_candidates c USING(candidate_id,response_id)
            JOIN core.model_responses m USING(response_id)
            JOIN core.model_runs r USING(model_run_id)
            WHERE q.review_status='unreviewed' ORDER BY q.candidate_id""").fetchall()
        for record in records:
            record['source_pages']=conn.execute("""SELECT p.*,e.document_sha256,e.clean_text,v.local_path
                FROM core.response_pages p JOIN core.page_extractions e USING(extraction_run_id,document_id,page_number)
                JOIN core.document_versions v ON v.document_id=e.document_id AND v.sha256=e.document_sha256
                WHERE p.response_id=%s ORDER BY p.input_position""",(record['response_id'],)).fetchall()
            record['model_evidence_claims']=conn.execute('SELECT * FROM core.requirement_evidence WHERE candidate_id=%s ORDER BY evidence_index',(record['candidate_id'],)).fetchall()
            record['review_to_complete']=dict(decision=None,reviewer=None,reviewed_at=None,approved_payload=None,notes=None)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dest=ROOT/'reports/candidate_review'/f'candidate_review_{stamp}.json'
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(dict(exported_at=stamp,notice='Draft review packet. No decisions have been made or imported.',candidates=records),indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    print('Unreviewed candidates exported:',len(records))
    print('Review packet:',dest)
    print('Database changes: none')


if __name__=='__main__':main()
