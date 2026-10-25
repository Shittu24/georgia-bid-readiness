select r.response_id,r.model_run_id,r.split,r.status,r.json_valid,r.schema_valid,r.generation_seconds,
r.input_tokens,r.output_tokens,r.output_budget_reached,r.receipt_id,r.artifact_sha256,
p.document_id,p.page_number target_page,d.solicitation_id
from {{ source('core','model_responses') }} r left join {{ source('core','response_pages') }} p
on p.response_id=r.response_id and p.page_role='target'
left join {{ ref('dim_document') }} d using(document_id)
