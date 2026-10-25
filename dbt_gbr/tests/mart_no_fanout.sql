select solicitation_id from {{ ref('mart_solicitation_overview') }} where
candidates<>accepted_candidates+rejected_candidates+followup_candidates+unreviewed_candidates
or invalid_responses>model_calls or canonical_groups>source_assertions
or unreviewed_splits>split_drafts
