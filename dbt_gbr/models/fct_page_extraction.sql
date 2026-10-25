select md5(p.extraction_run_id||':'||p.document_id||':'||p.page_number::text) page_extraction_key,
p.extraction_run_id,p.document_id,d.solicitation_id,p.page_number,
md5(p.document_id||':'||p.document_sha256) document_version_key,p.status,p.character_count,p.needs_review,
coalesce(r.review_status,'unreviewed') review_status,
(p.needs_review and coalesce(r.review_status,'unreviewed')<>'resolved') unresolved_flag
from {{ source('core','page_extractions') }} p join {{ ref('dim_document') }} d using(document_id)
left join lateral(select review_status from {{ source('core','page_reviews') }} r
where r.extraction_run_id=p.extraction_run_id and r.document_id=p.document_id and r.page_number=p.page_number
order by reviewed_at desc,review_id desc limit 1) r on true
