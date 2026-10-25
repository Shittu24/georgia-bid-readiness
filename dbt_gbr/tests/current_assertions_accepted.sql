select a.assertion_id from {{ ref('fct_canonical_assertion') }} a join {{ ref('fct_requirement_candidate') }} c using(candidate_id)
where a.review_is_current and (c.review_status<>'accepted' or c.review_event_id<>a.review_event_id)
