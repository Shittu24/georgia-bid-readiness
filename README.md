# Georgia Bid Readiness

An individual CS 7050 project by Ibrahim Shittu  
Kennesaw State University

## What this project does

Georgia Bid Readiness helps small businesses understand what a Georgia
government service solicitation requires.

The system collects solicitation documents and amendments, extracts their
contents, organizes the information in a warehouse, and presents a checklist
with supporting quotations and page references.

It helps answer:

- What must I do before submitting?
- What documents must I include?
- When and how must I submit?
- Which requirements apply only if I win?
- What changed in the amendments?
- What information is missing or unclear?

The application supports human review. It does not guarantee eligibility,
compliance, or a contract award.

## Example

A solicitation might say:

> Bidders must attend a mandatory site visit. Include a signed
> acknowledgement of all addenda with the proposal. Only the awarded
> contractor must provide proof of insurance before work begins.

The application should separate those instructions:

| Requirement | Stage |
|---|---|
| Attend the mandatory site visit | Before submission |
| Include signed addenda acknowledgement | At submission |
| Provide insurance before work starts | After award |

Each checklist item must point to its supporting document, page, and quotation.

This example is illustrative, not a quotation from our collected documents.

## Why this project matters

Bid instructions can be spread across an original solicitation, attachments,
and multiple amendments. A business may miss a required form, confuse an
opening date with a submission deadline, or apply an after-award requirement
too early.

This project brings those documents together and makes their requirements
easier to inspect and verify.

## Our approach

We are building the data engineering foundation on CPU first.

```text
Source pages and PDFs
        |
        v
Download and register documents
        |
        v
Preserve original files and versions
        |
        v
Extract text by page
        |
        +----> OCR when needed
        |
        v
Clean and validate records
        |
        v
Load the warehouse
        |
        v
Display documents and reviewed examples
        |
        v
Add and evaluate model extraction
        |
        v
Display evidence-backed requirement checklists
```

AI is one component of the project. The data pipeline, warehouse, provenance,
quality checks, and dashboard must work before we scale model experiments.

## Initial scope

### Intended user

A small service-business owner reviewing a government contract opportunity.

### First complete case

The Commerce janitorial solicitation and its amendments.

We will verify the collected packet against the source listing before
describing it as complete.

### Initial development sources

| Source | Pilot cases |
|---|---|
| City of Commerce | Janitorial, audit, and hotel-related solicitations |
| City of Tucker | Call-center solicitation |
| City of Richmond Hill | Debris-related solicitation |

Source pages:

- [Commerce bid opportunities](https://www.commercega.gov/business/bid-opportunities)
- [Tucker RFP 2025-007](https://www.tuckerga.gov/rfp/rfp-2025-007/)
- [Richmond Hill bid listing](https://www.richmondhill-ga.gov/bids.aspx?bidID=61)

These are collection sources, not ready-made labeled training datasets.
We will create reviewed requirement annotations from selected documents.

The pilot cases are development material. They will not serve as an
independent final test set after we use them to improve the system.

## What the first version will include

- Document collection from reviewed source URLs.
- Original PDF preservation.
- Duplicate detection using file hashes.
- Document version and amendment tracking.
- Page-level text extraction.
- OCR for pages that need it.
- Data-quality checks and processing logs.
- A relational warehouse and analytical queries.
- A Streamlit interface for browsing documents and requirements.
- Supporting evidence for every displayed requirement.
- Prompting experiments with saved results and GPU receipts.

During the CPU phase, requirement records will be manually reviewed examples,
clearly identified as human annotations.

## Outside the first version

- Statewide automated crawling.
- Automatic bid submission.
- Automatic proposal writing.
- Legal advice.
- Contract-award prediction.
- Automatic certification that a business qualifies.
- A continuously available GPU inference service.

LoRA fine-tuning is optional and depends on labeled data, time, and whether
it can improve on the prompting baseline.

## Important definitions

| Term | Meaning |
|---|---|
| Solicitation | One government purchasing opportunity |
| Document version | One observed version of a source file |
| Amendment | A document changing or clarifying a solicitation |
| Packet | The original solicitation and associated documents collected for it |
| Requirement | An explicitly stated action, document, or condition |
| Evidence | The quotation and page supporting a requirement |
| Processing run | One recorded execution of a pipeline stage |
| Human annotation | A requirement reviewed and recorded manually |
| Model prediction | A requirement extracted by an AI experiment |

Human annotations and model predictions must remain distinguishable.

## Requirement categories

Categories describe what a requirement concerns:

- Submission method and deadline.
- Mandatory meeting or site visit.
- Required forms and attachments.
- Addenda acknowledgement.
- Insurance, licensing, or certifications.
- Bonds or other financial requirements.
- Contractor obligations after award.

## Requirement stages

Stages describe when a requirement applies:

| Stage | Example |
|---|---|
| Before submission | Attend a mandatory site visit |
| At submission | Include a signed form |
| After award | Provide insurance before work begins |
| Needs clarification | Documents give conflicting deadlines |

Preserve conditions such as “awarded contractor only.”

Keep submission deadlines, meeting dates, and bid-opening dates separate.
Do not silently resolve contradictory information.

## Project structure

Some folders below are planned additions to the initial structure.

```text
georgia-bid-readiness/
├── README.md
├── configs/
├── data/
│   ├── raw/
│   ├── processed/
│   └── labels/
├── notebooks/
├── src/
│   ├── ingestion/
│   ├── extraction/
│   ├── transformation/
│   └── evaluation/
├── warehouse/
│   ├── ddl/
│   ├── models/
│   └── tests/
├── app/
├── experiments/
│   ├── runs/
│   └── receipts/
└── reports/
```

| Folder | Purpose |
|---|---|
| `configs/` | Paths and non-secret settings |
| `data/raw/` | Preserved original source files |
| `data/processed/` | Extracted text and transformed records |
| `data/labels/` | Reviewed annotations and dataset splits |
| `notebooks/` | Exploration and experiments |
| `src/` | Reusable pipeline code |
| `warehouse/` | Database definitions, transformations, and tests |
| `app/` | Streamlit application |
| `experiments/runs/` | Settings, predictions, timings, and results |
| `experiments/receipts/` | Copies of course GPU receipts |
| `reports/` | Scope, diagrams, findings, and final report |

Never store passwords or access tokens in committed configuration files.

## Planned tools

| Task | Tool |
|---|---|
| Pipeline development | Python |
| Version control | Git |
| PDF text extraction | pypdf |
| OCR | Tesseract and optionally OCRmyPDF |
| Warehouse | PostgreSQL |
| Transformations and data tests | SQL and dbt Core |
| Interface | Streamlit |
| Model experiments | PyTorch and Transformers |
| Model quantization | bitsandbytes |
| Optional LoRA | PEFT |
| GPU run tracking | Professor-provided `cs7050_receipt.py` |

Verify persistent PostgreSQL support in the school CPU environment before
choosing its hosting location. Local PostgreSQL is an alternative.

## CPU and GPU responsibilities

| CPU work | GPU work |
|---|---|
| Collect and register PDFs | Model inference experiments |
| Extract text and run OCR | Optional LoRA training |
| Clean and validate records | Model performance measurements |
| Build and query the warehouse | |
| Prepare and review annotations | |
| Calculate evaluation metrics | |
| Run the dashboard with saved results | |
| Prepare reports and charts | |

We can develop in the school environment and keep local backups.
Matching folder structures do not automatically synchronize their contents.

## Data engineering rules

1. Preserve original source files.
2. Record source URL, retrieval time, filename, file hash, and storage path.
3. Link every page to its document version.
4. Link originals and amendments to their solicitation.
5. Reprocessing unchanged data must not create duplicate records.
6. Preserve previous versions when source contents change.
7. Record failures and allow targeted retries.
8. Flag incomplete packets and conflicting information.
9. Keep raw text separate from cleaned text.
10. Keep human labels separate from model predictions.

## Warehouse design principles

Define what one row represents before creating each table.

Examples:

- One document-version row represents one observed version of a file.
- One page row represents one page of a document version.
- One requirement-extraction row represents one candidate requirement
  produced by one experiment.
- Evidence records connect requirements to supporting pages.

Planned source tables include solicitations, document versions, pages,
and pipeline runs.

The analytical model will support reporting by agency, solicitation,
document, date, requirement category, and model run.

## Project lifecycle

| Phase | Work | Main output |
|---|---|---|
| 1 | Define scope and success criteria | Scope and acceptance checklist |
| 2 | Establish folders, configuration, and backups | Reproducible workspace |
| 3 | Collect and register documents | Raw files and source manifest |
| 4 | Extract text and assess quality | Page-level text and quality flags |
| 5 | Build the warehouse | Schema and repeatable loads |
| 6 | Handle amendments and quality checks | Relationships and issue records |
| 7 | Build the initial interface | CPU dashboard |
| 8 | Create reviewed labels and fixed splits | Evaluation dataset |
| 9 | Compare prompting approaches | Predictions, metrics, and receipts |
| 10 | Assess optional LoRA | Fine-tuning comparison if justified |
| 11 | Integrate model results | Evidence-backed checklist |
| 12 | Complete report and demonstration | Final project and portfolio |

## Evaluation plan

Begin with 30–50 manually reviewed passages to refine annotation rules.

A later planning target is approximately 200–300 passages across around
30 solicitations, subject to availability and annotation effort.
This is a target, not a completed dataset.

Split data by solicitation. An original document and all its amendments
must remain in the same split.

- Training data: examples used for optional model training.
- Development data: examples used to improve prompts and choose settings.
- Test data: examples reserved for final evaluation.

Include fully reviewed packets so we can measure missed requirements.

Compare:

1. Rules-based extraction.
2. Basic prompting.
3. Improved prompting with examples and a defined output structure.
4. Optional LoRA, if justified.

Measure:

- Requirement precision and recall.
- Stage accuracy.
- Deadline accuracy.
- Whether evidence supports the extracted claim.
- Output-format validity.
- Generation time.
- GPU memory usage.

Valid JSON alone does not mean an extraction is correct.

## GPU experiment receipts

Wrap each GPU experiment with the professor’s recorder.

```python
from cs7050_receipt import record_run

with record_run(
    "experiment-label",
    netid="ishittu1",
    notes="Model, settings, and purpose",
) as run_id:
    # Actual GPU inference or training goes here.
    pass
```

The placeholder above is not an experiment by itself.

The recorder attempts to save receipts under:

```text
/home/shared/cs7050/receipts/ishittu1/
```

Its fallback is:

```text
~/.cs7050/receipts/ishittu1/
```

Use the printed `saved` path to locate the actual file.

Copy receipts into `experiments/receipts/` and save the same run ID with
predictions and evaluation results. Include receipt summaries in the
final report appendix.

Keep failed-run receipts too. Do not prolong experiments to satisfy a
minimum duration.

## Current starting point

As of October 16, 2026:

- The proposal has been accepted.
- School CPU and GPU access are available.
- The initial project folders have been created.
- Basic GPU and NF4 computation tests passed.
- A small model completed a synthetic extraction test.
- The synthetic extraction was inaccurate and slow.
- GPU receipt recording worked.
- We are now prioritizing the CPU data engineering foundation.

The synthetic test confirms execution, not model readiness.

Successful execution receipt:

```text
Run ID: d6df4636d5cf
Model: Qwen/Qwen2.5-1.5B-Instruct
Generation time: 414.48 seconds
Peak PyTorch allocated GPU memory: 1.648 GiB
```

The model omitted requirements, assigned an incorrect deadline, provided
mismatched evidence, and failed the requested output format.

Retain this as a development smoke test, not independent accuracy evidence.

## Completion checklist

- [ ] Unchanged files can be reprocessed without duplicate document versions.
- [ ] Changed files preserve earlier versions.
- [ ] Every extracted page links to its source document.
- [ ] Failed and low-quality extraction is visible.
- [ ] Amendments link to the correct solicitation.
- [ ] Conflicts are preserved for review.
- [ ] Every displayed requirement has evidence and a recorded origin.
- [ ] One complete packet works end to end in the dashboard.
- [ ] A local backup can restore essential project data.
- [ ] Final evaluation uses fixed, separate test solicitations.
- [ ] GPU results link to their receipts.
- [ ] The report explains findings, errors, and limitations.

## Effort budget

The course-sized core assumes a deliberately small corpus.

| Workstream | Estimated hours |
|---|---:|
| Scope, setup, and backups | 3 |
| Ingestion and text extraction | 7 |
| Warehouse, transformations, and quality | 8 |
| Initial labels and evaluation design | 7 |
| Prompting experiments and evaluation | 6 |
| Streamlit integration | 4 |
| Report and demonstration | 5 |
| Total | 40 |

Broader collection, expanded annotations, interface improvements, and LoRA
may add 20–40 hours or more.

Complete the core before committing to extensions.

## Immediate next step

Establish the CPU workspace, configuration, and backups.

Then inventory the existing pilot documents and build a source manifest.
Validate ingestion and repeat processing on one complete solicitation
packet before expanding the dataset.