"""Consistent PostgreSQL dump, isolated restore comparison, and project archive."""
from pathlib import Path
from datetime import datetime,timezone
import os,json,hashlib,uuid,subprocess,zipfile,shutil
import psycopg
from psycopg import sql
from de_common import ROOT,settings,pg_env,require

def stamp():return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
def binary(name):
 folder=Path(os.environ.get('GBR_PG_BIN','/home/jovyan/.conda/envs/gbr-postgres/bin'))
 p=folder/(name+('.exe' if os.name=='nt' else ''))
 require(p.is_file(),f'PostgreSQL tool missing: {p}')
 return str(p)
def fingerprints(conn):
 tables=conn.execute("""SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')
 AND schemaname NOT LIKE 'pg_toast%' ORDER BY 1,2""").fetchall()
 result={}
 for schema,table in tables:
  h=hashlib.sha256();n=0
  with conn.cursor() as cur:
   cur.execute(sql.SQL('SELECT row_to_json(t)::text FROM {}.{} t ORDER BY row_to_json(t)::text').format(sql.Identifier(schema),sql.Identifier(table)))
   for row in cur:
    h.update(row[0].encode());h.update(b'\n');n+=1
  result[schema+'.'+table]={'rows':n,'sha256':h.hexdigest()}
 return result
def database_backup(destination,verify=True):
 destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
 dump=destination/f'gbr_{stamp()}.dump';partial=dump.with_suffix('.partial')
 env=pg_env();env['PGOPTIONS']='-c timezone=UTC'
 with psycopg.connect(**settings()) as conn:
  conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  conn.execute("SET LOCAL TIME ZONE 'UTC'")
  snapshot=conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
  source=fingerprints(conn)
  subprocess.run([binary('pg_dump'),'-Fc','--no-owner','--no-privileges','--snapshot',snapshot,'--file',str(partial)],env=env,check=True,capture_output=True,text=True)
 partial.replace(dump)
 report={'dump':str(dump),'source_tables':source,'restore_verified':False}
 if verify:
  name='gbr_de_restore_'+uuid.uuid4().hex[:20];created=False
  admin_cfg=dict(settings());admin_cfg['dbname']='postgres'
  try:
   with psycopg.connect(**admin_cfg,autocommit=True) as admin:
    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));created=True
   subprocess.run([binary('pg_restore'),'--exit-on-error','--no-owner','--no-privileges','--dbname',name,str(dump)],env=env,check=True,capture_output=True,text=True)
   restored_cfg=dict(settings());restored_cfg['dbname']=name
   with psycopg.connect(**restored_cfg) as restored:
    restored.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');restored.execute("SET LOCAL TIME ZONE 'UTC'")
    result=fingerprints(restored)
   require(source==result,'Restore content comparison failed; backup retained for investigation')
   report.update(restore_verified=True,restored_tables=result,test_database=name)
  finally:
   if created:
    require(name.startswith('gbr_de_restore_') and name!=settings()['dbname'],'Unsafe restore cleanup target')
    with psycopg.connect(**admin_cfg,autocommit=True) as admin:
     admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
 path=dump.with_suffix('.verification.json');path.write_text(json.dumps(report,indent=2),encoding='utf-8')
 return report

def archive_project(destination):
 destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
 require(not destination.is_relative_to(ROOT),'Project archive destination must be outside project')
 excluded={'.git','__pycache__','.pytest_cache','.ipynb_checkpoints','node_modules','target','dbt_packages'}
 files=[]
 for folder,dirs,names in os.walk(ROOT,followlinks=False):
  dirs[:]=[d for d in dirs if d not in excluded and not d.startswith('.venv') and not (Path(folder)/d).is_symlink()]
  for name in names:
   path=Path(folder)/name
   if path.is_symlink() or name=='.env' or (name.startswith('.env.') and name!='.env.example'):continue
   files.append(path)
 require(shutil.disk_usage(destination).free>sum(p.stat().st_size for p in files)+128*1024*1024,'Insufficient space for project archive')
 output=destination/f'gbr_project_{stamp()}.zip';manifest={}
 with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
  for path in sorted(files):
   data=path.read_bytes();name=path.relative_to(ROOT).as_posix();z.writestr(name,data);manifest[name]=hashlib.sha256(data).hexdigest()
  z.writestr('_backup_manifest.json',json.dumps(manifest,indent=2))
 with zipfile.ZipFile(output) as z:
  require(z.testzip() is None,'Project ZIP CRC check failed')
  for name,digest in manifest.items():require(hashlib.sha256(z.read(name)).hexdigest()==digest,'Project ZIP content mismatch')
 return {'project_archive':str(output),'files_verified':len(manifest),'excluded':'Git metadata, virtual environments, caches, dbt targets and .env secrets'}
