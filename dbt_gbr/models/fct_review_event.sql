select r.review_event_id,r.candidate_id,r.decision,r.reviewer,r.review_method,r.reviewed_at,r.reviewed_at::date date_day,r.notes from {{ source('core','requirement_reviews') }} r
