"""Preview the approved review package; --commit persists it atomically."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,importlib.util,json
import psycopg

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('review_importer',ROOT/'src/transformation/review_importer.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package',type=Path,default=ROOT/'data/reviews/hotel_pilot_review_v1/approved_decisions.json')
    ap.add_argument('--commit',action='store_true')
    args=ap.parse_args();prepared=module.prepare(args.package)
    with psycopg.connect(**module.base.settings(),autocommit=True) as conn:
        report=module.import_reviews(conn,prepared,commit=args.commit)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path=ROOT/'reports/review_imports'/f'review_import_{stamp}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['counts'],indent=2));print('Mode:',report['mode']);print('Report:',path)

if __name__=='__main__':main()
