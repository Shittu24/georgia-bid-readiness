from pathlib import Path

import psycopg
from psycopg.rows import dict_row
import streamlit as st

PROJECT = Path(__file__).resolve().parents[1]

DB = {
    "host": "/home/jovyan/.gbr-pg-socket",
    "dbname": "georgia_bid_readiness",
    "user": "jovyan",
    "connect_timeout": 10,
}

st.set_page_config(
    page_title="Georgia Bid Readiness",
    page_icon="📄",
    layout="wide",
)

def query(statement, parameters=()):
    try:
        with psycopg.connect(**DB, row_factory=dict_row) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute(statement, parameters)
                return cursor.fetchall()
    except psycopg.Error as error:
        st.error("The warehouse could not be queried. Check PostgreSQL.")
        with st.expander("Connection details"):
            st.code(str(error))
        st.stop()

def document_label(document):
    if document["document_type"] == "original":
        return "Original solicitation"
    number = document["amendment_number"]
    return f"Addendum {number}" if number else document["document_type"]

st.title("Georgia Bid Readiness")
st.caption(
    "Explore solicitation documents, extracted pages, and processing quality. "
    "Requirement extraction will be added later."
)

solicitations = query("""
    SELECT solicitation_id, title, agency_name
    FROM core.solicitations
    ORDER BY agency_name, title
""")

if not solicitations:
    st.info("No solicitations have been loaded.")
    st.stop()

selected = st.sidebar.selectbox(
    "Solicitation",
    range(len(solicitations)),
    format_func=lambda i: (
        f"{solicitations[i]['agency_name']} — "
        f"{solicitations[i]['title']}"
    ),
)
solicitation = solicitations[selected]
sid = solicitation["solicitation_id"]

st.sidebar.button("Refresh data")
st.sidebar.caption("Read-only warehouse explorer • CPU")

inventory = query("""
    SELECT *
    FROM reporting.document_inventory
    WHERE solicitation_id = %s
    ORDER BY amendment_number NULLS FIRST, document_id, sha256
""", (sid,))

runs = query("""
    SELECT DISTINCT q.extraction_run_id, r.started_at
    FROM reporting.extraction_quality AS q
    JOIN core.pipeline_runs AS r ON r.run_id = q.extraction_run_id
    WHERE q.solicitation_id = %s
    ORDER BY r.started_at DESC NULLS LAST, q.extraction_run_id DESC
""", (sid,))

if not inventory or not runs:
    st.info("Documents and an extraction run are needed to show this dashboard.")
    st.stop()

run_id = st.sidebar.selectbox(
    "Extraction run",
    [row["extraction_run_id"] for row in runs],
)

quality = query("""
    SELECT *
    FROM reporting.extraction_quality
    WHERE solicitation_id = %s AND extraction_run_id = %s
""", (sid, run_id))

metrics = st.columns(4)
metrics[0].metric("Document versions stored", len(inventory))
metrics[1].metric(
    "Pages in selected run", sum(r["page_records"] for r in quality)
)
metrics[2].metric(
    "Extraction failures", sum(r["failed_pages"] for r in quality)
)
metrics[3].metric(
    "Unresolved flagged pages",
    sum(r["unresolved_flagged_pages"] for r in quality),
)

documents_tab, pages_tab, history_tab = st.tabs([
    "Documents", "Page explorer", "Processing history"
])

with documents_tab:
    st.subheader("Document inventory")
    st.caption(
        "All stored versions are shown. Repeated downloads are observations, "
        "not additional document versions."
    )
    st.dataframe(
        [{
            "Document": document_label(row),
            "Version": row["sha256"][:12],
            "Pages": row["page_count"],
            "Download observations": row["observation_count"],
            "First retrieved": row["first_retrieved_at"],
            "Last retrieved": row["last_retrieved_at"],
        } for row in inventory],
        hide_index=True,
        width="stretch",
    )

    st.subheader("Extraction quality for selected run")
    st.dataframe(
        [{
            "Document": row["document_id"],
            "Pages": row["page_records"],
            "Failures": row["failed_pages"],
            "Initially flagged": row["originally_flagged_pages"],
            "Resolved": row["resolved_flagged_pages"],
            "Unresolved": row["unresolved_flagged_pages"],
        } for row in quality],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "These checks describe processing quality. They do not certify "
        "that every sentence, form, or table was extracted correctly."
    )

with pages_tab:
    # Offer only versions actually present in the selected extraction run.
    extracted_versions = {
        (row["document_id"], row["document_sha256"])
        for row in quality
    }
    available = [
        row for row in inventory
        if (row["document_id"], row["sha256"]) in extracted_versions
    ]

    if not available:
        st.info("No document versions are available for this run.")
    else:
        choice = st.selectbox(
            "Document version",
            range(len(available)),
            format_func=lambda i: (
                f"{document_label(available[i])} — "
                f"{available[i]['sha256'][:12]}"
            ),
        )
        document = available[choice]

        pages = query("""
            SELECT p.*, r.review_status, r.resolution,
                   r.ocr_required, r.notes AS review_notes
            FROM core.page_extractions AS p
            LEFT JOIN LATERAL (
                SELECT review_status, resolution, ocr_required, notes
                FROM core.page_reviews
                WHERE extraction_run_id = p.extraction_run_id
                  AND document_id = p.document_id
                  AND page_number = p.page_number
                ORDER BY reviewed_at DESC, review_id DESC
                LIMIT 1
            ) AS r ON TRUE
            WHERE p.extraction_run_id = %s
              AND p.document_id = %s
              AND p.document_sha256 = %s
            ORDER BY p.page_number
        """, (run_id, document["document_id"], document["sha256"]))

        page_choice = st.selectbox(
            "PDF page",
            range(len(pages)),
            format_func=lambda i: str(pages[i]["page_number"]),
        )
        page = pages[page_choice]

        if page["status"] != "ok":
            st.error("Text extraction failed for this page.")
        elif page["needs_review"]:
            if (
                page["review_status"] == "resolved"
                and page["ocr_required"] is False
            ):
                st.success("Flag reviewed and resolved.")
                st.write(page["review_notes"])
            else:
                st.warning("This page needs review or OCR.")
        else:
            st.info("No automatic review flag was raised for this page.")

        st.caption(
            f"Original flags: {', '.join(page['quality_flags']) or 'None'}"
        )

        show_raw = st.checkbox("Show original extracted text")
        text = page["raw_text"] if show_raw else page["clean_text"]
        st.code(text or "[No extracted text]", language=None, wrap_lines=True)

        pdf = (PROJECT / document["local_path"]).resolve()
        if pdf.is_relative_to(PROJECT.resolve()) and pdf.is_file():
            st.download_button(
                "Download source PDF",
                data=pdf.read_bytes(),
                file_name=f"{document['document_id']}.pdf",
                mime="application/pdf",
            )
        else:
            st.warning("The source PDF is unavailable at its recorded path.")

with history_tab:
    st.subheader("Processing history")
    history = query("""
        SELECT h.run_id, h.run_type, h.parent_run_id, h.status,
               h.started_at, h.completed_at,
               h.document_observations, h.page_records
        FROM reporting.processing_history AS h
        WHERE EXISTS (
            SELECT 1
            FROM core.document_observations AS o
            JOIN core.documents AS d ON d.document_id = o.document_id
            WHERE o.run_id = h.run_id AND d.solicitation_id = %s
        )
        OR EXISTS (
            SELECT 1
            FROM core.page_extractions AS p
            JOIN core.documents AS d ON d.document_id = p.document_id
            WHERE p.extraction_run_id = h.run_id
              AND d.solicitation_id = %s
        )
        ORDER BY h.started_at, h.run_id
    """, (sid, sid))
    st.dataframe(history, hide_index=True, width="stretch")
    st.caption(
        "History is filtered to this solicitation. Counts describe entire "
        "runs, which may include more than one solicitation in future."
    )
