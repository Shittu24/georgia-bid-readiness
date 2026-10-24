"""Synthetic fixtures only; database test data is always rolled back."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import uuid

import pytest
import psycopg

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("requirement_loader", ROOT / "src/transformation/requirement_loader.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def bundle(tmp_path):
    sid = "test-" + uuid.uuid4().hex
    doc = sid + "-original"
    inputs = [dict(target_page_id=sid + str(n), document_id=doc, page_number=n,
                   context_pages=[dict(page_id=sid + str(n), page_number=n, is_target=True, text=text)])
              for n, text in [(1, "Sign the proposal."), (2, "Required Forms")]]
    snap = tmp_path / "data/labels/requirement_pilot_v1/snapshots" / sid
    snap.mkdir(parents=True)
    raw = "\n".join(json.dumps(i) for i in inputs).encode()
    (snap / "evaluation_inputs.jsonl").write_bytes(raw)
    write_json(snap / "snapshot_manifest.json", dict(snapshot_id=sid, snapshot_hashes={"evaluation_inputs.jsonl": loader.digest(raw)}))
    prompts = tmp_path / "experiments/requirement_pilot_v1/prompts_v2"
    schema = json.loads((ROOT / "tests/fixtures/requirement_output_schema.json").read_text(encoding="utf-8"))
    prefix = [{"role": "system", "content": "Synthetic extraction fixture"}]
    for name, value in [("output_schema.json", schema), ("zero_shot_prefix.json", prefix), ("two_shot_prefix.json", prefix)]:
        write_json(prompts / name, value)
    config = dict(snapshot_id=sid, model_id="synthetic", model_commit="test", prompt_version="v2",
                  input_hash=loader.digest(raw), prompt_hashes={p.name: loader.digest(p.read_bytes()) for p in prompts.glob("*.json")})
    folder = tmp_path / "experiments/requirement_pilot_v1/evaluation_v2"
    write_json(folder / "evaluation_config.json", config)
    config_hash = loader.digest((folder / "evaluation_config.json").read_bytes())
    for item in inputs:
        for approach in ("zero_shot", "two_shot"):
            bad = item["page_number"] == 2 and approach == "two_shot"
            predictions = [] if item["page_number"] == 2 else [dict(requirement="Sign proposal", condition=None, deadline_text=None,
                evidence=[dict(page_number=1, quote="Sign the proposal." if approach == "zero_shot" else "Invented quote")])]
            record = dict(status="completed", session_id=sid, target_page_id=item["target_page_id"], document_id=doc,
                page_number=item["page_number"], split="evaluation", approach=approach, evaluation_config_sha256=config_hash,
                messages=prefix + [dict(role="user", content=loader.target_message(item))], raw_response="[{" if bad else json.dumps(predictions),
                json_valid=not bad, schema_valid=not bad, input_tokens=20, output_tokens=10,
                generation_seconds=1.5, output_budget_reached=bad)
            if not bad:
                record.update(parsed_response=predictions, predicted_requirement_count=len(predictions))
            write_json(folder / f"{item['page_number']}_{approach}.json", record)
    return tmp_path


def test_preflight_preserves_invalid_and_empty_outputs(bundle):
    prepared = loader.prepare(bundle)
    assert len(prepared["responses"]) == 4
    assert sum(not r["schema_valid"] for r in prepared["responses"]) == 1
    assert sum(r["parsed"] == [] for r in prepared["responses"]) == 1


def test_tampered_prompt_rejected(bundle):
    p = bundle / "experiments/requirement_pilot_v1/prompts_v2/zero_shot_prefix.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Prompt checksum"):
        loader.prepare(bundle)


def test_tampered_input_rejected(bundle):
    p = next(bundle.glob("data/labels/requirement_pilot_v1/snapshots/*/evaluation_inputs.jsonl"))
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="input checksum"):
        loader.prepare(bundle)


def test_saved_flags_not_trusted(bundle):
    p = bundle / "experiments/requirement_pilot_v1/evaluation_v2/2_two_shot.json"
    data = loader.read_json(p); data["schema_valid"] = True; write_json(p, data)
    with pytest.raises(ValueError, match="validation flags"):
        loader.prepare(bundle)


def test_saved_messages_not_trusted(bundle):
    p = bundle / "experiments/requirement_pilot_v1/evaluation_v2/1_two_shot.json"
    data = loader.read_json(p); data["messages"][-1]["content"] += " altered"; write_json(p, data)
    with pytest.raises(ValueError, match="target message"):
        loader.prepare(bundle)


def test_missing_job_rejected(bundle):
    (bundle / "experiments/requirement_pilot_v1/evaluation_v2/2_two_shot.json").unlink()
    with pytest.raises(ValueError, match="Missing pilot"):
        loader.prepare(bundle)


def seed_sources(cur, prepared, suffix=""):
    """Create synthetic provenance for supplied fixture text, never a real PDF claim."""
    sid = "source-" + uuid.uuid4().hex
    cur.execute("INSERT INTO core.solicitations(solicitation_id,agency_name,solicitation_number,title,source_page_url) VALUES(%s,%s,%s,'Synthetic test','https://example.test')", (sid,sid,sid))
    er = sid + suffix
    cur.execute("INSERT INTO core.pipeline_runs(run_id,run_type,status,artifact_path) VALUES(%s,'extraction','ok','synthetic-test')", (er,))
    documents = {r["item"]["document_id"] for r in prepared["responses"]}
    for doc in documents:
        cur.execute("INSERT INTO core.documents(document_id,solicitation_id,document_type) VALUES(%s,%s,'original') ON CONFLICT DO NOTHING", (doc,sid))
        cur.execute("INSERT INTO core.document_versions(document_id,sha256,local_path,size_bytes,page_count) VALUES(%s,%s,'synthetic.pdf',1,100) ON CONFLICT DO NOTHING", (doc,"a"*64))
    pages = {(r["item"]["document_id"], p["page_number"]): p["text"] for r in prepared["responses"] for p in r["item"]["context_pages"]}
    for (doc, number), text in pages.items():
        cur.execute("""INSERT INTO core.page_extractions(extraction_run_id,document_id,document_sha256,page_number,
            extraction_method,extractor_version,status,raw_text,clean_text,needs_review)
            VALUES(%s,%s,%s,%s,'fixture','1','ok',%s,%s,false)""", (er,doc,"a"*64,number,text,text))
    return er


@pytest.fixture
def db(bundle):
    if os.environ.get("GBR_RUN_DB_TESTS") != "1":
        pytest.skip("Set GBR_RUN_DB_TESTS=1 with a migrated PostgreSQL database")
    with psycopg.connect(**loader.settings(), autocommit=True) as conn:
        with conn.transaction():
            prepared = loader.prepare(bundle)
            with conn.cursor() as cur:
                seed_sources(cur, prepared)
            yield conn, prepared
            raise psycopg.Rollback()


def count_responses(conn, prepared):
    ids = [r["response_id"] for r in prepared["responses"]]
    return conn.execute("SELECT count(*) FROM core.model_responses WHERE response_id=ANY(%s)", (ids,)).fetchone()[0]


def test_preview_rolls_back(db):
    conn, p = db
    report = loader.load(conn,p)
    assert report["mode"] == "preview_rolled_back"
    assert count_responses(conn,p) == 0


def test_repeat_load_and_bad_evidence(db):
    conn, p = db
    first = loader.load(conn,p,commit=True)
    second = loader.load(conn,p,commit=True)
    assert first["counts"]["model_responses_inserted"] == 4
    assert first["counts"]["requirement_candidates_inserted"] == 2
    assert first["counts"]["evidence_exact"] == 1
    assert first["counts"]["evidence_not_exact"] == 1
    assert count_responses(conn,p) == 4
    assert not any(v for k,v in second["counts"].items() if k.endswith("_inserted"))


def test_mid_batch_conflict_rolls_back(db):
    conn, p = db
    final = copy.deepcopy(p); final["responses"] = final["responses"][-1:]
    loader.load(conn,final,commit=True)
    changed = copy.deepcopy(p)
    changed["responses"][-1]["record"]["generation_seconds"] += 1
    with pytest.raises(ValueError, match="Conflicting existing record"):
        loader.load(conn,changed,commit=True)
    assert count_responses(conn,p) == 1


def test_missing_source_rolls_back(db):
    conn, p = db
    with pytest.raises(ValueError, match="Expected one source"):
        loader.load(conn,p,commit=True,run_overrides={p["responses"][0]["item"]["document_id"]: "nonexistent"})
    assert count_responses(conn,p) == 0


def test_ambiguous_source_rejected(db):
    conn, p = db
    with conn.cursor() as cur:
        seed_sources(cur,p,"duplicate")
    with pytest.raises(ValueError, match="found 2"):
        loader.load(conn,p,commit=True)
    assert count_responses(conn,p) == 0
