"""Apply only migration 003 to an existing core database, atomically."""
from pathlib import Path
import hashlib
import os
import psycopg

ROOT = Path(__file__).resolve().parents[1]

def settings():
    return dict(host=os.environ.get('PGHOST', '/home/jovyan/.gbr-pg-socket'),
                port=os.environ.get('PGPORT', '5432'),
                user=os.environ.get('PGUSER', 'jovyan'),
                dbname=os.environ.get('PGDATABASE', 'georgia_bid_readiness'),
                connect_timeout=10)

def apply(connection):
    path = ROOT / 'warehouse/ddl/003_canonical_requirements.sql'
    content = path.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    with connection.transaction():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7050, 4)")
            cur.execute("SELECT to_regclass('core.requirement_reviews')")
            if cur.fetchone()[0] is None:
                raise RuntimeError('Existing core schema not found; apply 001 and 002 first.')
            cur.execute('''CREATE TABLE IF NOT EXISTS core.schema_migrations (
                migration_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            cur.execute('SELECT sha256 FROM core.schema_migrations WHERE migration_id=%s',
                        ('003_canonical_requirements',))
            previous = cur.fetchone()
            if previous:
                if previous[0] != checksum:
                    raise RuntimeError('Applied migration checksum differs; do not edit an applied migration.')
                print('Migration 003 already applied; checksum verified.')
                return
            cur.execute(content.decode('utf-8'))
            cur.execute('INSERT INTO core.schema_migrations(migration_id,sha256) VALUES (%s,%s)',
                        ('003_canonical_requirements',checksum))
    print('Migration 003 applied successfully.')

if __name__ == '__main__':
    with psycopg.connect(**settings()) as conn:
        apply(conn)
