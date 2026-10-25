"""Populate only an explicitly authorized disposable CI database."""
import os
import tempfile
from pathlib import Path
import test_requirement_loader as base
import psycopg

if os.environ.get('GBR_CI_FIXTURE_DB') != '1' or not base.loader.settings()['dbname'].startswith('gbr_ci_'):
    raise SystemExit('Fixture seeding requires GBR_CI_FIXTURE_DB=1 and a gbr_ci_ database.')
with tempfile.TemporaryDirectory() as temp:
    folder = base.bundle.__wrapped__(Path(temp))
    prepared = base.loader.prepare(folder)
    with psycopg.connect(**base.loader.settings(), autocommit=True) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                base.seed_sources(cur, prepared)
                cur.execute('UPDATE core.document_versions SET page_count=2')
            base.loader.load(conn, prepared, commit=True)
print('Synthetic CI source pages and model outputs loaded.')
