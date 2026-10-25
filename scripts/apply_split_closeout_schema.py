"""Apply only migration 005 to an existing core database, atomically."""
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
    path = ROOT / 'warehouse/ddl/005_split_closeout.sql'
    content = path.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    with connection.transaction():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7050, 6)")
            cur.execute("SELECT to_regclass('core.split_requirements')")
            if cur.fetchone()[0] is None:
                raise RuntimeError('Existing core schema not found; apply 001 through 004 first.')
            cur.execute('''CREATE TABLE IF NOT EXISTS core.schema_migrations (
                migration_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            cur.execute('SELECT sha256 FROM core.schema_migrations WHERE migration_id=%s',
                        ('005_split_closeout',))
            previous = cur.fetchone()
            if previous:
                if previous[0] != checksum:
                    raise RuntimeError('Applied migration checksum differs; do not edit an applied migration.')
                print('Migration 005 already applied; checksum verified.')
                return
            cur.execute(content.decode('utf-8'))
            cur.execute('INSERT INTO core.schema_migrations(migration_id,sha256) VALUES (%s,%s)',
                        ('005_split_closeout',checksum))
    print('Migration 005 applied successfully.')

if __name__ == '__main__':
    with psycopg.connect(**settings()) as conn:
        apply(conn)
