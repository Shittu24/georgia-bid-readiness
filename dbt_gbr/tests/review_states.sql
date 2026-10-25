select candidate_id from {{ ref('fct_requirement_candidate') }} where review_status not in ('accepted','rejected','needs_followup','unreviewed')
or exact_quote_matches>evidence_claims or (review_status='accepted' and coalesce(length(trim(reviewed_requirement_text)),0)=0)
