"""Preview by default. Use --commit to persist validated pilot artifacts."""
import argparse
import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone
import psycopg

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("requirement_loader", ROOT / "src/transformation/requirement_loader.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--source-runs", type=Path, help="Optional JSON document_id -> extraction_run_id mapping for ambiguous sources")
    args = parser.parse_args()
    prepared = loader.prepare(args.project)
    overrides = loader.read_json(args.source_runs) if args.source_runs else None
    with psycopg.connect(**loader.settings(), autocommit=True) as conn:
        report = loader.load(conn, prepared, commit=args.commit, run_overrides=overrides)
    report["configuration_sha256"] = prepared["config_hash"]
    report["snapshot_id"] = prepared["config"]["snapshot_id"]
    report["source_run_overrides"] = overrides
    report["artifact_hashes"] = {r["artifact_path"]: r["artifact_sha256"] for r in prepared["responses"]}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = args.project / "reports/requirement_loads" / f"pilot_{stamp}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"], indent=2))
    print("Mode:", report["mode"])
    print("Report:", destination)


if __name__ == "__main__":
    main()
