from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
import re

from pypdf import PdfReader


def extract_packet(project, manifest_path, low_text_threshold=100):
    project = Path(project).resolve()
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if not manifest.get("packet_download_complete"):
        raise ValueError("The input packet has incomplete downloads.")

    sid = manifest["solicitation_id"]
    if not re.fullmatch(r"[a-z0-9-]+", sid):
        raise ValueError("Invalid solicitation ID.")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project / "data/processed/text" / sid / run_id
    output.mkdir(parents=True, exist_ok=False)

    extractor_version = metadata.version("pypdf")
    pages_path = output / "pages.jsonl"
    summary_path = output / "extraction_summary.json"

    summary = {
        "extraction_run_id": run_id,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "solicitation_id": sid,
        "input_manifest": manifest_path.relative_to(project).as_posix(),
        "extractor": "pypdf",
        "extractor_version": extractor_version,
        "low_text_threshold": low_text_threshold,
        "expected_pages": manifest["total_pages"],
        "page_records_written": 0,
        "successful_pages": 0,
        "failed_pages": 0,
        "pages_needing_review": 0,
        "all_pages_extracted": False,
        "status": "running",
        "documents": [],
    }

    def save_summary():
        temporary = summary_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        temporary.replace(summary_path)

    save_summary()

    with pages_path.open("w", encoding="utf-8") as page_file:
        for document in manifest["records"]:
            document_id = document["document_id"]
            records = []

            try:
                if document["status"] != "ok":
                    raise ValueError("Document was not downloaded successfully.")

                pdf_path = (project / document["local_path"]).resolve()
                if not pdf_path.is_relative_to(project):
                    raise ValueError("PDF path is outside the project.")

                digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
                if digest != document["sha256"]:
                    raise ValueError("PDF hash differs from the manifest.")

                reader = PdfReader(pdf_path)
                if reader.is_encrypted:
                    raise ValueError("Encrypted PDF requires review.")

                if len(reader.pages) != document["page_count"]:
                    raise ValueError("PDF page count differs from the manifest.")

                for number, page in enumerate(reader.pages, start=1):
                    record = {
                        "extraction_run_id": run_id,
                        "document_id": document_id,
                        "solicitation_id": sid,
                        "document_sha256": digest,
                        "source_url": document["source_url"],
                        "source_pdf": document["local_path"],
                        "page_number": number,
                        "extraction_method": "pypdf",
                        "extractor_version": extractor_version,
                    }

                    try:
                        raw_text = page.extract_text() or ""
                        clean_text = raw_text.replace("\r\n", "\n")
                        clean_text = clean_text.replace("\r", "\n")
                        clean_text = re.sub(r"[ \t]+", " ", clean_text)
                        clean_text = "\n".join(
                            line.strip() for line in clean_text.splitlines()
                        ).strip()

                        characters = len(re.sub(r"\s", "", raw_text))
                        flags = []

                        if not raw_text.strip():
                            flags.append("empty_text")
                        elif characters < low_text_threshold:
                            flags.append("low_text")

                        record.update({
                            "status": "ok",
                            "raw_text": raw_text,
                            "clean_text": clean_text,
                            "character_count": len(raw_text),
                            "non_whitespace_characters": characters,
                            "quality_flags": flags,
                            "needs_review": bool(flags),
                        })

                    except Exception as error:
                        record.update({
                            "status": "failed",
                            "raw_text": None,
                            "clean_text": None,
                            "character_count": None,
                            "non_whitespace_characters": None,
                            "quality_flags": ["extraction_error"],
                            "needs_review": True,
                            "error": str(error),
                        })

                    page_file.write(
                        json.dumps(record, ensure_ascii=False) + "\n"
                    )
                    page_file.flush()
                    records.append(record)

                    summary["page_records_written"] += 1
                    summary["successful_pages"] += int(record["status"] == "ok")
                    summary["failed_pages"] += int(record["status"] == "failed")
                    summary["pages_needing_review"] += int(record["needs_review"])

                failures = sum(r["status"] == "failed" for r in records)
                flagged = sum(r["needs_review"] for r in records)

                summary["documents"].append({
                    "document_id": document_id,
                    "status": "partial_failure" if failures else "ok",
                    "page_count": len(records),
                    "failed_pages": failures,
                    "pages_needing_review": flagged,
                })

                print(
                    f"{document_id}: {len(records)} pages, "
                    f"{flagged} flagged for review",
                    flush=True,
                )

            except Exception as error:
                summary["documents"].append({
                    "document_id": document_id,
                    "status": "failed",
                    "error": str(error),
                })
                print(f"FAILED | {document_id} | {error}", flush=True)

            save_summary()

    summary["all_pages_extracted"] = (
        summary["successful_pages"] == summary["expected_pages"]
        and all(d["status"] == "ok" for d in summary["documents"])
    )
    summary["status"] = (
        "ok" if summary["all_pages_extracted"] else "partial_failure"
    )
    summary["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_summary()

    return output, summary
