select m.solicitation_id from {{ ref('mart_de_closeout') }} m where
 m.outstanding_followups<0 or m.distinct_requirements>m.current_source_assertions
 or m.current_source_assertions<>(select count(*) from {{ ref('fct_current_requirement_assertion') }} a where a.solicitation_id=m.solicitation_id)
 or m.distinct_requirements<>(select count(distinct canonical_id) from {{ ref('fct_current_requirement_assertion') }} a where a.solicitation_id=m.solicitation_id)
