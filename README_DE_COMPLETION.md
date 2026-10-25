# Georgia Bid Readiness — DE completion package

Upload this package into the existing `/home/jovyan/project/georgia-bid-readiness` project. Open **notebooks/10_de_completion_dbt.ipynb** and run its cells in order on the school **CPU** environment. The GPU is not needed.

This is an additive extension, not a replacement project. It requires the previously installed requirement loader, canonical schema, approved-review importer, their tests, and the committed 32 review decisions. Your source PDFs, annotations, model outputs and existing Streamlit app remain in place.

## What this completes

```text
Existing PDFs → ingestion → page extraction → PostgreSQL source records
                                               ↓
Saved model outputs → evidence checks → human review history
                                               ↓
                         approved canonical groups / pending split drafts
                                               ↓
                          dbt dimensions + facts + solicitation summary
                                               ↓
                          quality tests → report → verified backup
```

The new Python runner refreshes the warehouse from **already loaded** sources and reviews. It does not download new solicitations, run extraction, call an LLM, or use a paid API. Run the existing ingestion/extraction/load process first when adding documents. The reviewed grouping plan is specific to the current hotel pilot; expanding that plan requires reviewed decisions for the new records.

Included: migration 004 with evidence-checked split drafts; repeat-safe canonical grouping; 14 dbt models and 35 dbt data tests; a staged Python runner with logs and a concurrency lock; HTML/JSON reports; database dumps with isolated restore/content verification; project ZIP backup; a CPU notebook; and an additive GitHub Actions workflow.

## Expected pilot state after the school run

| Record | Expected count |
|---|---:|
| Source solicitations / documents / extracted page records | 2 / 15 / 47 |
| Model responses / requirement candidates | 14 / 32 |
| Existing review decisions | 32 |
| Accepted / rejected / needs follow-up candidates | 14 / 15 / 3 |
| Canonical groups / source assertions | 13 / 14 |
| Proposed split requirements / origin links | 4 / 6 |
| Human reviews of the new splits | 0 |
| Confirmed amendment relationships | 0 |

These are record counts, **not accuracy, recall, or completeness scores**. Fourteen accepted candidates are not necessarily fourteen distinct obligations. Two accepted source assertions describe the same deadline. The four split drafts separate signing and returning addenda, but need their own human decisions. No amendment relationship is invented merely because a document is an addendum.

## Running it

The notebook creates `.venv-de` from the CPU Python installation and installs `requirements-de.txt` there. It does not upgrade your notebook, GPU, or dashboard environment. It adds Git exclusions without replacing the existing `.gitignore`.

PostgreSQL must already be running. If it stopped when the school session restarted, use the same startup procedure you have verified:

```bash
mkdir -p /home/jovyan/.gbr-pg-socket
chmod 0700 /home/jovyan/project/georgia-bid-readiness-db /home/jovyan/.gbr-pg-socket
chmod g-s /home/jovyan/project/georgia-bid-readiness-db /home/jovyan/.gbr-pg-socket
/home/jovyan/.conda/envs/gbr-postgres/bin/pg_ctl \
  -D /home/jovyan/project/georgia-bid-readiness-db \
  -l /home/jovyan/project/georgia-bid-readiness-db/server.log \
  -o "-c listen_addresses='' -k /home/jovyan/.gbr-pg-socket" -w start
```

Do not initialize a new database or delete the existing data directory. The notebook first checks connectivity, then backs up before applying migration 004. It runs the 40 integration tests using synthetic rows that roll back. It previews new groups/drafts, runs the full refresh, and verifies a repeated grouping load adds no records.

After first setup, normal refresh is:

```bash
cd /home/jovyan/project/georgia-bid-readiness
.venv-de/bin/python scripts/run_de_pipeline.py run
```

`check` checks prerequisites. `preview` checks the grouping plan and rolls back new groups/splits (requires migration 004 already applied). `run` commits the approved grouping and unapproved drafts, builds/tests dbt models, generates reports and verifies backups. Each stage has its own transaction or output; the entire run is **not** one database transaction. If a later stage fails, inspect its log, fix the cause and rerun. Earlier successful stages may remain committed, and loaders detect repeat records or conflicting changes.

## Outputs and analytical design

Each run writes `reports/de_runs/<timestamp>/run_report.json`, individual stage logs, dbt artifacts, and `warehouse_summary.html` / `.json`. A successful full run has `status: complete`. Open the HTML through Jupyter to inspect results; it is a data-engineering report, not the finished bidder-facing service.

Models are built in `analytics_gbr`:

- Dimensions: solicitation, document, document version, model run, and operational date.
- Facts: processing run, page extraction, model response, requirement candidate, review event, canonical assertion, split requirement, and amendment relationship.
- Mart: solicitation overview, with independent aggregates to prevent inflated totals from joins.

Page-extraction totals count extraction **records**, including historical runs. They should not be presented as unique current pages after reprocessing. Review-event totals include history; candidate status uses the latest review. Canonical assertions expose whether their approval remains current. The date dimension covers recorded operational dates, not normalized procurement deadlines. The original source tables and detailed lineage remain authoritative.

## Backups and recovery

Backups go outside the Git project to `../georgia-bid-readiness-backups/de_completion/`. Database snapshots include all user tables. Verification restores into a new uniquely named temporary database, compares table row counts **and content hashes**, then removes only that temporary database. It requires permission to create databases (the account previously used for your restore checks has this).

Project ZIPs contain project files with a SHA-256 manifest and are checked after writing. They exclude Git metadata, virtual environments, caches, generated dbt targets and `.env` secrets. Other files are included, so keep credentials out of source files and notebooks. The final run report is completed after the archive stage; download that report separately as well. Keep a downloaded backup outside the school storage. These backups do not replace backing up credentials separately or preserving the Git remote.

If restore verification fails, stop and inspect the report; do not restore over the live database. The `.dump` can be restored to a separate empty database with `pg_restore --exit-on-error --no-owner --no-privileges`. Connection settings use normal `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, and optional `PGPASSWORD` variables. `GBR_PG_BIN` overrides the PostgreSQL binary directory.

## Validation and finish criteria

Local validation: 40 Python tests passed; two full pipeline runs passed using the real saved model/review artifacts and synthetic source database rows; each built 14 models and passed 35 dbt tests, with repeat checks and database restore verification. Local testing used Python 3.12 and PostgreSQL 18. It did **not** connect to your school database or verify your full 47-page corpus. School Python 3.11/PostgreSQL 17 validation is performed by the notebook. See `reports/de_package_validation/` for the local evidence.

The new GitHub workflow uses Python 3.11 and PostgreSQL 17 with disposable synthetic data. It has not been run on your GitHub account yet. Commit the package after the school run and confirm the workflow is green. Do not commit `.venv-de`, database dumps or generated dbt target folders.

This DE milestone is complete when the school notebook passes, the run report says complete, the source counts remain correct, and backups are downloaded. Remaining product work includes approving the split drafts, expanding reviewed coverage and amendment decisions, improving/evaluating extraction, bidder-profile matching, and integrating the validated results into the final app. The dbt layer does not make a bid-readiness decision by itself.

References: [dbt build](https://docs.getdbt.com/reference/commands/build), [PostgreSQL connection setup](https://docs.getdbt.com/docs/local/connect-data-platform/postgres-setup).
