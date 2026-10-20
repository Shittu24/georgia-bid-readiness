from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote
from datetime import datetime, timezone
import hashlib
import io
import json
import re
import time

import requests
from pypdf import PdfReader


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def ingest(project, config_path):
    project = Path(project).resolve()
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    sid = config["solicitation_id"]

    if not re.fullmatch(r"[a-z0-9-]+", sid):
        raise ValueError("Invalid solicitation ID.")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    raw = project / "data/raw" / sid
    manifests = project / "data/processed/manifests"
    raw.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)

    manifest_path = manifests / f"{sid}_{run_id}.json"
    manifest = {
        "schema_version": 1,
        "ingestion_run_id": run_id,
        "started_at_utc": utc_now(),
        "solicitation_id": sid,
        "solicitation_number": config["solicitation_number"],
        "title": config["title"],
        "agency": config["agency"],
        "source_page": config["source_page"],
        "configuration": config,
        "expected_document_count": 1 + len(config["expected_addenda"]),
        "packet_download_complete": False,
        "status": "running",
        "records": [],
    }
    save_json(manifest_path, manifest)

    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "GeorgiaBidReadiness/0.1 (academic document collection)"
        })

        try:
            listing = session.get(
                config["source_page"], timeout=(15, 60)
            )
            listing.raise_for_status()

            snapshot = raw / f"source_listing_{run_id}.html"
            snapshot.write_bytes(listing.content)
            manifest["source_listing_snapshot"] = (
                snapshot.relative_to(project).as_posix()
            )
            manifest["source_listing_sha256"] = hashlib.sha256(
                listing.content
            ).hexdigest()

            parser = LinkCollector()
            parser.feed(listing.text)
            documents = []
            seen = set()

            for href in parser.links:
                url = urljoin(listing.url, href)
                path = unquote(urlsplit(url).path)
                filename = path.rsplit("/", 1)[-1]

                if f"/{config['folder_name']}/" not in path:
                    continue
                if not filename.lower().endswith(".pdf") or url in seen:
                    continue
                seen.add(url)

                match = re.search(r"ADDENDUM\s*#?\s*(\d+)", filename, re.I)

                if filename == config["original_filename"]:
                    number = None
                    kind = "original"
                    document_id = f"{sid}-original"
                elif match:
                    number = int(match.group(1))
                    kind = "addendum"
                    document_id = f"{sid}-addendum-{number:02d}"
                else:
                    continue

                documents.append({
                    "document_id": document_id,
                    "solicitation_id": sid,
                    "agency": config["agency"],
                    "document_type": kind,
                    "amendment_number": number,
                    "source_filename": filename,
                    "source_url": url,
                    "source_page": config["source_page"],
                })

            documents.sort(key=lambda d: d["amendment_number"] or 0)
            originals = [d for d in documents if d["document_type"] == "original"]
            numbers = [
                d["amendment_number"] for d in documents
                if d["document_type"] == "addendum"
            ]

            manifest["discovered_documents"] = documents
            save_json(manifest_path, manifest)

            if (
                len(originals) != 1
                or sorted(numbers) != sorted(config["expected_addenda"])
            ):
                raise ValueError(
                    f"Unexpected listing: {len(originals)} originals; "
                    f"amendments {numbers}. Review the source."
                )

        except Exception as error:
            manifest.update({
                "status": "failed",
                "error": str(error),
                "completed_at_utc": utc_now(),
            })
            save_json(manifest_path, manifest)
            raise

        for document in documents:
            record = {
                **document,
                "attempted_at_utc": utc_now(),
                "status": "pending",
            }

            try:
                response = session.get(
                    document["source_url"], timeout=(15, 90)
                )
                record.update({
                    "http_status": response.status_code,
                    "resolved_url": response.url,
                    "content_type": response.headers.get("Content-Type"),
                })
                response.raise_for_status()
                content = response.content

                if b"%PDF-" not in content[:1024]:
                    raise ValueError("Response has no PDF header.")

                reader = PdfReader(io.BytesIO(content))
                if reader.is_encrypted:
                    raise ValueError("Encrypted PDF requires review.")

                pages = len(reader.pages)
                if pages == 0:
                    raise ValueError("PDF contains no pages.")

                digest = hashlib.sha256(content).hexdigest()
                destination = raw / f"{document['document_id']}__{digest}.pdf"

                if destination.exists():
                    stored_hash = hashlib.sha256(
                        destination.read_bytes()
                    ).hexdigest()
                    if stored_hash != digest:
                        raise ValueError("Stored file failed its hash check.")
                    action = "reused_identical_file"
                else:
                    temporary = destination.with_suffix(".part")
                    temporary.write_bytes(content)
                    temporary.replace(destination)
                    action = "saved_new_version"

                record.update({
                    "status": "ok",
                    "retrieved_at_utc": utc_now(),
                    "sha256": digest,
                    "size_bytes": len(content),
                    "page_count": pages,
                    "local_path": destination.relative_to(project).as_posix(),
                    "storage_action": action,
                })
                print(
                    f"OK | {document['document_id']} | "
                    f"{pages} pages | {action}",
                    flush=True,
                )

            except Exception as error:
                record.update({
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                })
                print(
                    f"FAILED | {document['document_id']} | {error}",
                    flush=True,
                )

            manifest["records"].append(record)
            save_json(manifest_path, manifest)
            time.sleep(1)

    successful = [r for r in manifest["records"] if r["status"] == "ok"]
    failed = [r for r in manifest["records"] if r["status"] == "failed"]
    complete = (
        len(successful) == manifest["expected_document_count"]
        and not failed
    )

    manifest.update({
        "completed_at_utc": utc_now(),
        "successful_document_count": len(successful),
        "failed_document_count": len(failed),
        "total_pages": sum(r["page_count"] for r in successful),
        "packet_download_complete": complete,
        "status": "ok" if complete else "partial_failure",
    })
    save_json(manifest_path, manifest)
    return manifest_path, manifest
