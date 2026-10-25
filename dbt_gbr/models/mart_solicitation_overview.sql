with docs as(select solicitation_id,count(*) documents from {{ ref('dim_document') }} group by 1),
pages as(select solicitation_id,count(*) extraction_records,count(*) filter(where status='failed') extraction_failures,
count(*) filter(where unresolved_flag) unresolved_page_flags from {{ ref('fct_page_extraction') }} group by 1),
calls as(select solicitation_id,count(*) model_calls,count(*) filter(where not schema_valid) invalid_responses from {{ ref('fct_model_response') }} group by 1),
candidates as(select solicitation_id,count(*) candidates,count(*) filter(where review_status='accepted') accepted_candidates,
count(*) filter(where review_status='rejected') rejected_candidates,count(*) filter(where review_status='needs_followup') followup_candidates,
count(*) filter(where review_status='unreviewed') unreviewed_candidates from {{ ref('fct_requirement_candidate') }} group by 1),
canon as(select solicitation_id,count(distinct canonical_id) canonical_groups,count(*) source_assertions
from {{ ref('fct_canonical_assertion') }} where review_is_current group by 1),
splits as(select solicitation_id,count(*) split_drafts,count(*) filter(where review_status='unreviewed') unreviewed_splits from {{ ref('fct_split_requirement') }} group by 1)
select s.solicitation_id,s.agency_name,s.solicitation_number,s.title,
coalesce(d.documents,0) documents,coalesce(p.extraction_records,0) extraction_records,
coalesce(p.extraction_failures,0) extraction_failures,coalesce(p.unresolved_page_flags,0) unresolved_page_flags,
coalesce(m.model_calls,0) model_calls,coalesce(m.invalid_responses,0) invalid_responses,
coalesce(c.candidates,0) candidates,coalesce(c.accepted_candidates,0) accepted_candidates,
coalesce(c.rejected_candidates,0) rejected_candidates,coalesce(c.followup_candidates,0) followup_candidates,
coalesce(c.unreviewed_candidates,0) unreviewed_candidates,coalesce(a.canonical_groups,0) canonical_groups,
coalesce(a.source_assertions,0) source_assertions,coalesce(x.split_drafts,0) split_drafts,coalesce(x.unreviewed_splits,0) unreviewed_splits
from {{ ref('dim_solicitation') }} s left join docs d using(solicitation_id) left join pages p using(solicitation_id)
left join calls m using(solicitation_id) left join candidates c using(solicitation_id)
left join canon a using(solicitation_id) left join splits x using(solicitation_id)
