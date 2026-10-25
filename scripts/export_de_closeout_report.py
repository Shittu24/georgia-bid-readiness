"""Verify the hotel closeout state and export an auditable report."""
from datetime import datetime,timezone
from pathlib import Path
import json,html,os
import psycopg
from psycopg import sql
from de_common import ROOT,settings,require

if __name__=='__main__':
 sid='commerce-ga-26-008'
 with psycopg.connect(**settings()) as conn:
  schema=os.environ.get('GBR_ANALYTICS_SCHEMA','analytics_gbr')
  cur=conn.execute(sql.SQL('SELECT * FROM {}.mart_de_closeout WHERE solicitation_id=%s').format(sql.Identifier(schema)),(sid,))
  row=cur.fetchone();require(row is not None,'Closeout mart row missing; run dbt first')
  metrics=dict(zip([c.name for c in cur.description],row))
  expected=dict(documents=3,extraction_records=19,extraction_failures=0,unresolved_page_flags=0,distinct_requirements=17,current_source_assertions=18,historical_followup_candidates=3,followups_resolved_by_split=3,outstanding_followups=0,accepted_splits=4,pending_splits=0)
  for key,value in expected.items():require(metrics[key]==value,f'Unexpected {key}: {metrics[key]} (expected {value})')
  live=conn.execute('SELECT count(*),count(distinct canonical_id) FROM reporting.current_requirement_assertions WHERE solicitation_id=%s',(sid,)).fetchone()
  require(live==(18,17),'Live reviewed state differs from materialized mart; rebuild and inspect')
  require(conn.execute('SELECT count(*) FROM reporting.split_parent_resolution WHERE resolved_by_split').fetchone()[0]==3,'Live parent resolution differs')
  require(conn.execute('SELECT count(*) FROM reporting.split_requirement_status WHERE solicitation_id=%s AND review_status=\'accepted\'',(sid,)).fetchone()[0]==4,'Live split approvals differ')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
 folder=ROOT/'reports/de_closeout'/stamp;folder.mkdir(parents=True)
 report=dict(status='pilot_de_closeout_verified',recorded_at=stamp,metrics=metrics,scope='Current hotel pilot reviewed requirement population only; not extraction completeness or model accuracy.',history='Three combined parent candidates retain needs_followup in immutable review history; all three are operationally resolved by four approved splits.')
 (folder/'closeout_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 body='<html><meta charset="utf-8"><title>DE closeout</title><style>body{font:16px system-ui;margin:40px;max-width:900px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}</style><h1>Georgia Bid Readiness — DE closeout</h1><p>'+html.escape(report['scope'])+'</p><table>'
 body+=''.join('<tr><th>'+html.escape(k)+'</th><td>'+html.escape(str(v))+'</td></tr>' for k,v in metrics.items())
 body+='</table><p>'+html.escape(report['history'])+'</p></html>'
 (folder/'closeout_report.html').write_text(body,encoding='utf-8')
 print(json.dumps(report,indent=2));print('Report folder:',folder)
