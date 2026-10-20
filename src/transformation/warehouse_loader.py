from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def checked_path(project, relative):
    path = (project / relative).resolve()
    if not path.is_relative_to(project):
        raise ValueError("Artifact path is outside the project.")
    return path


def run_time(run_id):
    return datetime.strptime(
        run_id, "%Y%m%dT%H%M%S%fZ"
    ).replace(tzinfo=timezone.utc)


def insert_or_verify(cursor, table, values):
    """Preserve identical records; reject conflicting existing records."""
    cursor.execute(
        sql.SQL("""
            INSERT INTO {} ({}) VALUES ({})
            ON CONFLICT DO NOTHING
        """).format(
            sql.Identifier("core", table),
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )

    if cursor.rowcount == 1:
        return

    conditions = sql.SQL(" AND ").join(
        sql.SQL("{} IS NOT DISTINCT FROM %s").format(sql.Identifier(key))
        for key in values
    )
    cursor.execute(
        sql.SQL("SELECT 1 FROM {} WHERE {} LIMIT 1").format(
            sql.Identifier("core", table), conditions
        ),
        list(values.values()),
    )

    if cursor.fetchone() is None:
        raise ValueError(
            f"Conflicting existing record in core.{table}; "
            "the transaction will be rolled back."
        )


def load_packet(project, extraction_dir, db_settings):
    project = Path(project).resolve()
    extraction_dir = Path(extraction_dir).resolve()

    if not extraction_dir.is_relative_to(project):
        raise ValueError("Extraction directory is outside the project.")

    summary_path = extraction_dir / "extraction_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest_path = checked_path(project, summary["input_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # This first reusable loader accepts complete runs.
    if not manifest.get("packet_download_complete"):
        raise ValueError("Ingestion is incomplete.")
    if not summary.get("all_pages_extracted"):
        raise ValueError("Extraction is incomplete.")

    sid = manifest["solicitation_id"]
    ingestion_id = manifest["ingestion_run_id"]
    extraction_id = summary["extraction_run_id"]
    documents = manifest["records"]
    pages = read_jsonl(extraction_dir / "pages.jsonl")

    review_path = extraction_dir / "page_reviews.jsonl"
    reviews = read_jsonl(review_path) if review_path.exists() else []

    if len(documents) != manifest["expected_document_count"]:
        raise ValueError("Unexpected document count.")

    by_document = {d["document_id"]: d for d in documents}
    if len(by_document) != len(documents):
        raise ValueError("Duplicate document IDs in the manifest.")

    for document in documents:
        if document["status"] != "ok" or document["solicitation_id"] != sid:
            raise ValueError("Invalid document record.")

        source = checked_path(project, document["local_path"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != document["sha256"]:
            raise ValueError(f"Source hash mismatch: {document['document_id']}")

    page_lookup = {}
    for page in pages:
        key = (page["document_id"], page["page_number"])
        document = by_document.get(page["document_id"])

        if key in page_lookup:
            raise ValueError("Duplicate page record.")
        if (
            document is None
            or page["extraction_run_id"] != extraction_id
            or page["solicitation_id"] != sid
            or page["document_sha256"] != document["sha256"]
            or page["status"] != "ok"
        ):
            raise ValueError("Page record does not match the input packet.")

        page_lookup[key] = page

    for document in documents:
        actual = sorted(
            p["page_number"] for p in pages
            if p["document_id"] == document["document_id"]
        )
        if actual != list(range(1, document["page_count"] + 1)):
            raise ValueError("Missing or unexpected page numbers.")

    if len(pages) != summary["expected_pages"]:
        raise ValueError("Page count differs from extraction summary.")

    for review in reviews:
        page = page_lookup.get((review["document_id"], review["page_number"]))
        if (
            page is None
            or review["extraction_run_id"] != extraction_id
            or review["document_sha256"] != page["document_sha256"]
        ):
            raise ValueError("Review does not match its extracted page.")

    with psycopg.connect(**db_settings) as connection:
        with connection.cursor() as cursor:
            def put(table, values):
                insert_or_verify(cursor, table, values)

            put("solicitations", {
                "solicitation_id": sid,
                "agency_name": manifest["agency"],
                "solicitation_number": manifest["solicitation_number"],
                "title": manifest["title"],
                "source_page_url": manifest["source_page"],
            })

            put("pipeline_runs", {
                "run_id": ingestion_id,
                "run_type": "ingestion",
                "status": "ok",
                "started_at": manifest.get("started_at_utc") or run_time(ingestion_id),
                "completed_at": manifest["completed_at_utc"],
                "artifact_path": manifest_path.relative_to(project).as_posix(),
                "metadata": Jsonb({
                    "expected_document_count": manifest["expected_document_count"],
                    "source_listing_sha256": manifest["source_listing_sha256"],
                }),
            })

            for document in documents:
                put("documents", {
                    "document_id": document["document_id"],
                    "solicitation_id": sid,
                    "document_type": document["document_type"],
                    "amendment_number": document["amendment_number"],
                })
                put("document_versions", {
                    "document_id": document["document_id"],
                    "sha256": document["sha256"],
                    "local_path": document["local_path"],
                    "size_bytes": document["size_bytes"],
                    "page_count": document["page_count"],
                })
                put("document_observations", {
                    "run_id": ingestion_id,
                    "document_id": document["document_id"],
                    "version_sha256": document["sha256"],
                    "source_url": document["source_url"],
                    "source_filename": document["source_filename"],
                    "resolved_url": document.get("resolved_url"),
                    "attempted_at": document["attempted_at_utc"],
                    "retrieved_at": document["retrieved_at_utc"],
                    "http_status": document.get("http_status"),
                    "status": "ok",
                    "storage_action": document["storage_action"],
                })

            put("pipeline_runs", {
                "run_id": extraction_id,
                "run_type": "extraction",
                "parent_run_id": ingestion_id,
                "status": "ok",
                "started_at": summary.get("started_at_utc") or run_time(extraction_id),
                "completed_at": summary["completed_at_utc"],
                "artifact_path": summary_path.relative_to(project).as_posix(),
                "metadata": Jsonb({
                    "extractor": summary["extractor"],
                    "extractor_version": summary["extractor_version"],
                    "low_text_threshold": summary["low_text_threshold"],
                    "expected_pages": summary["expected_pages"],
                }),
            })

            page_fields = [
                "extraction_run_id", "document_id", "document_sha256",
                "page_number", "extraction_method", "extractor_version",
                "status", "raw_text", "clean_text", "character_count",
                "non_whitespace_characters", "needs_review",
            ]

            for page in pages:
                values = {key: page[key] for key in page_fields}
                values["quality_flags"] = Jsonb(page["quality_flags"])
                values["error_message"] = page.get("error")
                put("page_extractions", values)

            for review in reviews:
                values = {
                    key: review[key] for key in [
                        "extraction_run_id", "document_id", "page_number",
                        "review_status", "resolution", "ocr_required",
                        "reviewed_by", "review_method", "notes",
                    ]
                }
                values["reviewed_at"] = review["reviewed_at_utc"]
                put("page_reviews", values)

    return {
        "solicitation_id": sid,
        "input_documents": len(documents),
        "input_pages": len(pages),
        "input_reviews": len(reviews),
        "ingestion_run_id": ingestion_id,
        "extraction_run_id": extraction_id,
        "status": "committed",
    }
