select 'candidate_count' issue where (select count(*) from {{ ref('fct_requirement_candidate') }})<>(select count(*) from {{ source('core','requirement_candidates') }})
union all select 'review_count' where (select count(*) from {{ ref('fct_review_event') }})<>(select count(*) from {{ source('core','requirement_reviews') }})
union all select 'page_count' where (select count(*) from {{ ref('fct_page_extraction') }})<>(select count(*) from {{ source('core','page_extractions') }})
