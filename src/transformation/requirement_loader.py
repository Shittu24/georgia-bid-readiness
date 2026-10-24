"""Import the frozen v2 pilot. No inference, gold-label reads, or approvals.

This adapter deliberately fails closed for other artifact formats.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import os
import re

import jsonschema
from psycopg import sql
from psycopg.types.json import Jsonb


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def target_message(item):
    sections = [f"DOCUMENT: {item['document_id']}\nTARGET PDF PAGE: {item['page_number']}"]
    for page in item["context_pages"]:
        label = "TARGET" if page["is_target"] else "PRECEDING CONTEXT"
        sections.append(f"--- {label}: PDF PAGE {page['page_number']} ---\n{page['text']}")
    sections.append("--- END OF DOCUMENT TEXT ---\nExtract every in-scope obligation from the target page. Return only the JSON array of objects.")
    return "\n\n".join(sections)


def prepare(project):
    """Read once and validate provenance/structure before any database writes."""
    project = Path(project).resolve()
    base = project / "experiments/requirement_pilot_v1"
    folder = base / "evaluation_v2"
    config_path = folder / "evaluation_config.json"
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    config_hash = digest(config_bytes)
    snapshot_id = config["snapshot_id"]
    require(re.fullmatch(r"[A-Za-z0-9_-]+", snapshot_id), "Unsafe snapshot id")
    snapshot = project / "data/labels/requirement_pilot_v1/snapshots" / snapshot_id
    manifest = read_json(snapshot / "snapshot_manifest.json")
    require(manifest["snapshot_id"] == snapshot_id, "Snapshot identity mismatch")
    input_path = snapshot / "evaluation_inputs.jsonl"
    input_bytes = input_path.read_bytes()
    require(digest(input_bytes) == config["input_hash"] == manifest["snapshot_hashes"][input_path.name], "Frozen input checksum mismatch")
    prompts = base / "prompts_v2"
    prompt_values = {}
    for name in ("output_schema.json", "zero_shot_prefix.json", "two_shot_prefix.json"):
        raw = (prompts / name).read_bytes()
        require(digest(raw) == config["prompt_hashes"][name], f"Prompt checksum mismatch: {name}")
        prompt_values[name] = json.loads(raw)
    schema = prompt_values["output_schema.json"]
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    inputs = [json.loads(line) for line in input_bytes.decode("utf-8").splitlines() if line.strip()]
    by_id = {item["target_page_id"]: item for item in inputs}
    require(len(by_id) == len(inputs), "Duplicate frozen target id")
    for item in inputs:
        pages = item["context_pages"]
        targets = [p for p in pages if p["is_target"]]
        require(len(targets) == 1, "Expected exactly one target page")
        require(targets[0]["page_number"] == item["page_number"] and targets[0]["page_id"] == item["target_page_id"], "Target identity mismatch")
        require(len({p['page_number'] for p in pages}) == len(pages), "Duplicate input page")
        require(all(p["is_target"] or p["page_number"] == item["page_number"] - 1 for p in pages), "Unexpected context policy")
    responses = []
    seen = set()
    for path in sorted(folder.glob("*.json")):
        if path == config_path:
            continue
        raw = path.read_bytes()
        record = json.loads(raw)
        require(record["status"] == "completed", f"Unsupported call status: {path.name}")
        require(record["split"] == "evaluation", "Unexpected split")
        require(record["evaluation_config_sha256"] == config_hash, "Response configuration hash mismatch")
        approach = record["approach"]
        require(approach in ("zero_shot", "two_shot"), "Unexpected approach")
        item = by_id[record["target_page_id"]]
        require((item["document_id"], item["page_number"]) == (record["document_id"], record["page_number"]), "Response target mismatch")
        key = (item["target_page_id"], approach)
        require(key not in seen, "Duplicate pilot job")
        seen.add(key)
        messages = record["messages"]
        require(messages[:-1] == prompt_values[f"{approach}_prefix.json"], "Saved prefix differs from frozen prompt")
        require(messages[-1] == {"role": "user", "content": target_message(item)}, "Saved target message differs from frozen input")
        parsed = None
        errors = []
        try:
            parsed = json.loads(record["raw_response"], parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            json_valid = True
        except (ValueError, TypeError) as exc:
            json_valid = False
            errors.append(str(exc))
        if json_valid:
            errors = [e.message for e in validator.iter_errors(parsed)]
        schema_valid = json_valid and not errors
        require(record["json_valid"] == json_valid and record["schema_valid"] == schema_valid, "Saved validation flags disagree with recomputation")
        if json_valid:
            require(record.get("parsed_response") == parsed, "Saved parsed response differs from raw JSON")
        if schema_valid:
            require(record["predicted_requirement_count"] == len(parsed), "Candidate count mismatch")
            for pred in parsed:
                require(pred["requirement"].strip() and all(e["quote"].strip() for e in pred["evidence"]), "Blank candidate or evidence")
        identity = [record["session_id"], record["target_page_id"], approach]
        response_id = "pilot-" + digest(json.dumps(identity, separators=(",", ":")).encode())
        responses.append(dict(record=record, item=item, parsed=parsed, json_valid=json_valid,
                              schema_valid=schema_valid, errors=errors, response_id=response_id,
                              artifact_path=path.relative_to(project).as_posix(), artifact_sha256=digest(raw)))
    require(seen == {(i, a) for i in by_id for a in ("zero_shot", "two_shot")}, "Missing pilot jobs")
    return dict(config=config, config_hash=config_hash, config_path=config_path.relative_to(project).as_posix(), responses=responses)


def insert_or_verify(cur, table, key_columns, values):
    """Stable keys; a differing reimport is an error, never an update."""
    columns = list(values)
    def params():
        return [Jsonb(v) if isinstance(v, (dict, list)) else v for v in values.values()]
    query = sql.SQL("INSERT INTO core.{} ({}) VALUES ({}) ON CONFLICT DO NOTHING RETURNING 1").format(
        sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
        sql.SQL(",").join(sql.Placeholder() for _ in columns))
    cur.execute(query, params())
    if cur.fetchone():
        return True
    predicates = sql.SQL(" AND ").join(sql.SQL("{} IS NOT DISTINCT FROM %s").format(sql.Identifier(c)) for c in columns)
    cur.execute(sql.SQL("SELECT 1 FROM core.{} WHERE ").format(sql.Identifier(table)) + predicates, params())
    require(cur.fetchone() is not None, f"Conflicting existing record in {table}: " + repr({k: values[k] for k in key_columns}))
    return False


def resolve_pages(cur, item, run_overrides=None):
    result = []
    for position, page in enumerate(item["context_pages"], 1):
        cur.execute("""SELECT extraction_run_id, clean_text FROM core.page_extractions
                       WHERE document_id=%s AND page_number=%s AND status='ok'""",
                    (item["document_id"], page["page_number"]))
        rows = cur.fetchall()
        selected_run = (run_overrides or {}).get(item["document_id"])
        matches = [(run, text) for run, text in rows if text is not None and text.strip() == page["text"]
                   and (selected_run is None or run == selected_run)]
        require(len(matches) == 1, f"Expected one source extraction for {item['document_id']} page {page['page_number']}; found {len(matches)}. No source guessed.")
        run, text = matches[0]
        result.append(dict(input_position=position, page_role="target" if page["is_target"] else "context",
                           extraction_run_id=run, document_id=item["document_id"], page_number=page["page_number"],
                           text_sha256=digest(page["text"].encode("utf-8")), source_text=text))
    return result


def load(conn, prepared, *, commit=False, run_overrides=None):
    """Whole batch is atomic. Default rolls back even a successful preview."""
    import psycopg
    counts = Counter()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7050, 3)")
            config = prepared["config"]
            for response in prepared["responses"]:
                r = response["record"]
                run_id = "pilot-config-" + prepared["config_hash"] + "-" + r["approach"]
                def put(table, keys, values):
                    inserted = insert_or_verify(cur, table, keys, values)
                    counts[table + ("_inserted" if inserted else "_reused")] += 1
                put("model_runs", ["model_run_id"], dict(model_run_id=run_id, model_id=config["model_id"],
                    model_revision=config["model_commit"], prompt_version=config["prompt_version"], approach=r["approach"],
                    config_sha256=prepared["config_hash"], configuration=config, dataset_snapshot_id=config["snapshot_id"],
                    artifact_path=prepared["config_path"]))
                rid = response["response_id"]
                put("model_responses", ["response_id"], dict(response_id=rid, model_run_id=run_id,
                    split=r["split"], status=r["status"], raw_response=r["raw_response"], parsed_response=response["parsed"],
                    json_valid=response["json_valid"], schema_valid=response["schema_valid"],
                    error_message="; ".join(response["errors"]) or None,
                    generation_seconds=r["generation_seconds"], input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
                    output_budget_reached=r["output_budget_reached"],
                    artifact_path=response["artifact_path"], artifact_sha256=response["artifact_sha256"]))
                pages = resolve_pages(cur, response["item"], run_overrides)
                for page in pages:
                    put("response_pages", ["response_id", "input_position"], dict(response_id=rid, **{k:v for k,v in page.items() if k != "source_text"}))
                counts["responses_checked"] += 1
                if not response["schema_valid"]:
                    counts["invalid_responses_preserved"] += 1
                    continue
                for index, pred in enumerate(response["parsed"], 1):
                    cid = f"{rid}-{index}"
                    put("requirement_candidates", ["candidate_id"], dict(candidate_id=cid, response_id=rid,
                        output_index=index, requirement_text=pred["requirement"], condition_text=pred["condition"],
                        deadline_text=pred["deadline_text"], original_prediction=pred))
                    for eindex, evidence in enumerate(pred["evidence"], 1):
                        page = next((p for p in pages if p["page_number"] == evidence["page_number"]), None)
                        exact = page is not None and evidence["quote"] in page["source_text"]
                        put("requirement_evidence", ["candidate_id", "evidence_index"], dict(candidate_id=cid,
                            response_id=rid, evidence_index=eindex, claimed_page_number=evidence["page_number"],
                            quote_text=evidence["quote"], mapped_input_position=page["input_position"] if page else None,
                            exact_quote_match=exact, validation_notes="Substring only; semantic review pending." if exact
                            else "Quote absent from claimed source page." if page else "Claimed page not in target/context inputs."))
                        counts["evidence_exact" if exact else "evidence_not_exact"] += 1
            if not commit:
                raise psycopg.Rollback()
    return dict(mode="committed" if commit else "preview_rolled_back", counts=dict(counts))


def settings():
    return dict(host=os.environ.get("PGHOST", "/home/jovyan/.gbr-pg-socket"),
                port=os.environ.get("PGPORT", "5432"), user=os.environ.get("PGUSER", "jovyan"),
                dbname=os.environ.get("PGDATABASE", "georgia_bid_readiness"), connect_timeout=10)
