select c.candidate_id,c.response_id,m.solicitation_id,m.document_id,c.output_index,c.requirement_text,
coalesce(r.decision,'unreviewed') review_status,r.review_event_id,r.reviewed_at,
r.approved_payload->>'requirement' reviewed_requirement_text,
coalesce(e.claims,0) evidence_claims,coalesce(e.exact,0) exact_quote_matches
from {{ source('core','requirement_candidates') }} c join {{ ref('fct_model_response') }} m using(response_id)
left join lateral(select review_event_id,decision,reviewed_at,approved_payload from {{ source('core','requirement_reviews') }} rr
where rr.candidate_id=c.candidate_id order by reviewed_at desc,recorded_order desc limit 1) r on true
left join lateral(select count(*) claims,count(*) filter(where exact_quote_match) exact
from {{ source('core','requirement_evidence') }} e where e.candidate_id=c.candidate_id) e on true
