"""Refresh the reviewed warehouse into dbt marts. No GPU or web scraping."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,os,sys,subprocess,html,shutil
import psycopg
from psycopg import sql
from de_common import ROOT,settings,pg_env,plan,require,load_module
from de_backup import database_backup,archive_project,binary

def execute(cmd,log,env=None):
 with open(log,'w',encoding='utf-8') as output:
  result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,text=True)
 if result.returncode:
  tail=Path(log).read_text(encoding='utf-8',errors='replace')[-5000:]
  raise RuntimeError(f'Stage failed; see {log}\n{tail}')

def preflight(conn):
 for name in ['core.canonical_assertions','core.requirement_reviews','core.page_extractions']:
  require(conn.execute('SELECT to_regclass(%s)',(name,)).fetchone()[0] is not None,f'Missing prerequisite: {name}')
 p=plan();ids=[m['candidate_id'] for g in p['groups'] for m in g['members']]
 rows=conn.execute('SELECT candidate_id,review_status FROM reporting.requirement_review_queue WHERE candidate_id=ANY(%s)',(ids,)).fetchall()
 require(len(rows)==14 and all(r[1]=='accepted' for r in rows),'Expected 14 approved pilot candidates; complete review import first')
 for tool in ['pg_dump','pg_restore']:binary(tool)
 require(shutil.disk_usage(ROOT).free>512*1024*1024,'Less than 512 MB free; free space before continuing')
 return {'database':settings()['dbname'],'approved_candidates':len(rows),'free_disk_bytes':shutil.disk_usage(ROOT).free}

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['check','preview','run']);args=ap.parse_args()
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');folder=ROOT/'reports/de_runs'/stamp;folder.mkdir(parents=True)
 report={'run_id':stamp,'mode':args.mode,'status':'running','stages':[]}
 env=pg_env();env['DBT_SEND_ANONYMOUS_USAGE_STATS']='false'
 cfg=ROOT/'dbt_gbr';dbt=Path(sys.executable).parent/('dbt.exe' if os.name=='nt' else 'dbt')
 report_path=folder/'run_report.json'
 def stage(name,fn):
  record={'name':name,'started_at':datetime.now(timezone.utc).isoformat()};report['stages'].append(record)
  try:record['result']=fn();record['status']='ok'
  except Exception as e:record['status']='failed';record['error']=str(e);raise
  finally:record['finished_at']=datetime.now(timezone.utc).isoformat();report_path.write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
 def command(name,cmd):return stage(name,lambda:execute(cmd,folder/f'{name}.log',env))
 backup_root=ROOT.parent/(ROOT.name+'-backups')/'de_completion'
 try:
  with psycopg.connect(**settings(),autocommit=True) as lock:
   require(lock.execute('SELECT pg_try_advisory_lock(7050,90)').fetchone()[0],'Another DE pipeline is running')
   stage('preflight',lambda:preflight(lock))
   if args.mode=='check':report['status']='checked';return
   require(dbt.is_file(),'dbt executable missing; run the setup notebook first')
   if args.mode=='run':stage('before_change_backup',lambda:database_backup(backup_root,verify=False))
   if args.mode=='preview':
    require(lock.execute("SELECT to_regclass('core.split_requirements')").fetchone()[0] is not None,'Apply migration 004 via notebook before preview')
   else:command('migration_004',[sys.executable,str(ROOT/'scripts/apply_de_completion_schema.py')])
   command('reviewed_requirements',[sys.executable,str(ROOT/'scripts/complete_reviewed_requirements.py')]+(['--commit'] if args.mode=='run' else []))
   if args.mode=='preview':report['status']='preview_complete_no_group_or_split_writes';return
   command('dbt_build',[str(dbt),'build','--project-dir',str(cfg),'--profiles-dir',str(cfg)])
   shutil.copyfile(cfg/'target/run_results.json',folder/'dbt_build_results.json')
   command('dbt_docs',[str(dbt),'docs','generate','--project-dir',str(cfg),'--profiles-dir',str(cfg)])
   for name in ['manifest.json','run_results.json','catalog.json','index.html']:
    path=cfg/'target'/name
    if path.exists():shutil.copyfile(path,folder/name)
   schema=os.environ.get('GBR_ANALYTICS_SCHEMA','analytics_gbr')
   with lock.cursor() as cur:
    cur.execute(sql.SQL('SELECT * FROM {}.mart_solicitation_overview ORDER BY solicitation_id').format(sql.Identifier(schema)))
    cols=[c.name for c in cur.description];rows=cur.fetchall()
   summary=[dict(zip(cols,r)) for r in rows]
   (folder/'warehouse_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
   content='<html><meta charset="utf-8"><title>Georgia Bid DE Report</title><style>body{font:16px system-ui;margin:35px}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:8px}th{text-align:left}</style><h1>Georgia Bid Readiness — DE report</h1><p>Operational counts, not model accuracy or bid readiness. Split drafts and follow-up reviews remain pending.</p>'
   for row in summary:content+='<h2>'+html.escape(str(row['title']))+'</h2><table>'+''.join('<tr><th>'+html.escape(k)+'</th><td>'+html.escape(str(v))+'</td></tr>' for k,v in row.items())+'</table>'
   (folder/'warehouse_summary.html').write_text(content+'</html>',encoding='utf-8')
   stage('restore_verification',lambda:database_backup(backup_root,verify=True))
   stage('project_archive',lambda:archive_project(backup_root))
   report['status']='complete';print('DE refresh, dbt tests, and restore verification passed.')
 except Exception as exc:
  report['status']='failed';report['error']=str(exc);raise
 finally:
  report['finished_at']=datetime.now(timezone.utc).isoformat();report_path.write_text(json.dumps(report,indent=2,default=str),encoding='utf-8');print('Run report:',report_path)

if __name__=='__main__':main()
