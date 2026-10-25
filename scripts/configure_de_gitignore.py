"""Add DE-generated paths without replacing existing Git exclusions."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
path = root / '.gitignore'
existing = path.read_text(encoding='utf-8') if path.exists() else ''
patterns = ['.venv-de/', 'dbt_gbr/target/', 'dbt_gbr/logs/', 'dbt_gbr/dbt_packages/']
missing = [p for p in patterns if p not in existing.splitlines()]
if missing:
    path.write_text(existing.rstrip() + '\n\n# DE runtime and generated dbt files\n' + '\n'.join(missing) + '\n', encoding='utf-8')
print('Git exclusions ready.')
