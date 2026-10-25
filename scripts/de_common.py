from pathlib import Path
import importlib.util,os,json,hashlib
ROOT=Path(__file__).resolve().parents[1]

def load_module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

loader=load_module('existing_requirement_loader',ROOT/'src/transformation/requirement_loader.py')
def settings():return loader.settings()
def require(ok,message):
 if not ok:raise ValueError(message)
def plan():
 p=ROOT/'configs/de_completion_plan.json';raw=p.read_bytes()
 require(hashlib.sha256(raw).hexdigest()==p.with_suffix('.sha256').read_text().strip(),'DE plan checksum changed')
 return json.loads(raw)
def pg_env():
 e=os.environ.copy()
 for k,v in settings().items():
  if k in ('host','port','user','dbname'):e[{'host':'PGHOST','port':'PGPORT','user':'PGUSER','dbname':'PGDATABASE'}[k]]=str(v)
 return e
