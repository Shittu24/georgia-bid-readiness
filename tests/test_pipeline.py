from pathlib import Path
import importlib.util
import io
import json
import os
import uuid

import pytest
from pypdf import PdfWriter

PROJECT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT / relative_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingestion = load_module("commerce_ingestion", "src/ingestion/commerce.py")
extraction = load_module("pdf_extraction", "src/extraction/pdf_text.py")
loader = load_module(
    "warehouse_loader", "src/transformation/warehouse_loader.py"
)


def make_pdf(page_count=1):
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def packet(tmp_path, monkeypatch):
    """A small fake website and a real generated PDF."""
    config = {
        "solicitation_id": "test-packet",
        "solicitation_number": "TEST-001",
        "title": "Test solicitation",
        "agency": "Test agency",
        "source_page": "https://example.test/bids",
        "folder_name": "Test Packet",
        "original_filename": "original.pdf",
        "expected_addenda": [],
    }

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    website = {
        "html": (
            '<a href="/Test%20Packet/original.pdf">'
            "Original</a>"
        ),
        "pdf": make_pdf(),
    }

    class FakeResponse:
        def __init__(self, url):
            self.url = url
            self.status_code = 200
            is_listing = url == config["source_page"]
            self.content = (
                website["html"].encode()
                if is_listing else website["pdf"]
            )
            self.text = website["html"] if is_listing else ""
            self.headers = {
                "Content-Type": (
                    "text/html" if is_listing else "application/pdf"
                )
            }

        def raise_for_status(self):
            pass

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, timeout=None):
            return FakeResponse(url)

    monkeypatch.setattr(ingestion.requests, "Session", FakeSession)
    monkeypatch.setattr(ingestion.time, "sleep", lambda seconds: None)

    return tmp_path, config_path, website


def test_repeat_download_reuses_file(packet):
    project, config_path, _ = packet

    _, first = ingestion.ingest(project, config_path)
    _, second = ingestion.ingest(project, config_path)

    assert first["packet_download_complete"]
    assert second["packet_download_complete"]
    assert first["records"][0]["storage_action"] == "saved_new_version"
    assert second["records"][0]["storage_action"] == "reused_identical_file"
    assert first["records"][0]["sha256"] == second["records"][0]["sha256"]

    files = list((project / "data/raw/test-packet").glob("*.pdf"))
    assert len(files) == 1


def test_changed_pdf_preserves_previous_version(packet):
    project, config_path, website = packet

    _, first = ingestion.ingest(project, config_path)
    original_path = project / first["records"][0]["local_path"]
    original_bytes = original_path.read_bytes()

    website["pdf"] = make_pdf(page_count=2)
    _, second = ingestion.ingest(project, config_path)

    assert second["records"][0]["storage_action"] == "saved_new_version"
    assert first["records"][0]["sha256"] != second["records"][0]["sha256"]
    assert original_path.read_bytes() == original_bytes
    assert second["records"][0]["page_count"] == 2

    files = list((project / "data/raw/test-packet").glob("*.pdf"))
    assert len(files) == 2


def test_unexpected_amendment_stops_ingestion(packet):
    project, config_path, website = packet
    website["html"] += (
        '<a href="/Test%20Packet/ADDENDUM%201.pdf">Addendum</a>'
    )

    with pytest.raises(ValueError, match="Unexpected listing"):
        ingestion.ingest(project, config_path)

    manifests = list(
        (project / "data/processed/manifests").glob("*.json")
    )
    assert len(manifests) == 1

    recorded = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert recorded["status"] == "failed"
    assert recorded["packet_download_complete"] is False
    assert "Unexpected listing" in recorded["error"]
    assert not list((project / "data/raw/test-packet").glob("*.pdf"))


def test_page_count_mismatch_is_not_complete(packet):
    project, config_path, _ = packet
    manifest_path, manifest = ingestion.ingest(project, config_path)

    # Deliberately make the manifest disagree with its one-page PDF.
    manifest["records"][0]["page_count"] = 2
    manifest["total_pages"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    output, summary = extraction.extract_packet(project, manifest_path)

    assert summary["all_pages_extracted"] is False
    assert summary["status"] == "partial_failure"
    assert summary["documents"][0]["status"] == "failed"
    assert "page count" in summary["documents"][0]["error"].lower()
    assert (output / "extraction_summary.json").is_file()


@pytest.mark.skipif(
    os.environ.get("GBR_RUN_DB_TESTS") != "1",
    reason="Set GBR_RUN_DB_TESTS=1 to enable the PostgreSQL test.",
)
def test_database_conflict_rolls_back():
    """Use a unique test record and verify transaction rollback."""
    import psycopg

    settings = {
        "host": os.environ.get("PGHOST", "/home/jovyan/.gbr-pg-socket"),
        "dbname": os.environ.get("PGDATABASE", "georgia_bid_readiness"),
        "user": os.environ.get("PGUSER", "jovyan"),
        "port": os.environ.get("PGPORT", "5432"),
        "connect_timeout": 10,
    }
    if os.environ.get("PGPASSWORD"):
        settings["password"] = os.environ["PGPASSWORD"]

    token = uuid.uuid4().hex
    record = {
        "solicitation_id": f"automated-test-{token}",
        "agency_name": "Automated test agency",
        "solicitation_number": token,
        "title": "Original test title",
        "source_page_url": "https://example.test/",
    }

    with pytest.raises(ValueError, match="Conflicting existing record"):
        with psycopg.connect(**settings) as connection:
            with connection.cursor() as cursor:
                loader.insert_or_verify(cursor, "solicitations", record)

                # An identical retry must be accepted.
                loader.insert_or_verify(cursor, "solicitations", record)

                # Same key but changed content must raise an error.
                conflicting = {**record, "title": "Different title"}
                loader.insert_or_verify(
                    cursor, "solicitations", conflicting
                )

    with psycopg.connect(**settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM core.solicitations "
                "WHERE solicitation_id = %s",
                (record["solicitation_id"],),
            )
            assert cursor.fetchone()[0] == 0
