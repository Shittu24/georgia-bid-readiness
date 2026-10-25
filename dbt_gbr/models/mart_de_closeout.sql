with requirements as (
 select solicitation_id,count(*) source_assertions,count(distinct canonical_id) distinct_requirements
 from {{ ref('fct_current_requirement_assertion') }} group by 1
), resolved as (
 select c.solicitation_id,count(*) filter(where r.resolved_by_split) resolved_parents
 from {{ ref('fct_requirement_candidate') }} c join {{ ref('fct_split_parent_resolution') }} r using(candidate_id) group by 1
), splits as (
 select solicitation_id,count(*) filter(where review_status='accepted') accepted_splits,
 count(*) filter(where review_status<>'accepted') pending_splits
 from {{ ref('fct_split_requirement') }} group by 1
)
select m.solicitation_id,m.title,m.documents,m.extraction_records,m.extraction_failures,m.unresolved_page_flags,
coalesce(r.distinct_requirements,0) distinct_requirements,coalesce(r.source_assertions,0) current_source_assertions,
m.followup_candidates historical_followup_candidates,coalesce(q.resolved_parents,0) followups_resolved_by_split,
m.followup_candidates-coalesce(q.resolved_parents,0) outstanding_followups,
coalesce(s.accepted_splits,0) accepted_splits,coalesce(s.pending_splits,0) pending_splits
from {{ ref('mart_solicitation_overview') }} m left join requirements r using(solicitation_id)
left join resolved q using(solicitation_id) left join splits s using(solicitation_id)
