select d.document_id id from {{ ref('dim_document') }} d left join {{ ref('dim_solicitation') }} s using(solicitation_id) where s.solicitation_id is null
union all select p.page_extraction_key from {{ ref('fct_page_extraction') }} p left join {{ ref('dim_document_version') }} v using(document_version_key) where v.document_version_key is null
union all select c.candidate_id from {{ ref('fct_requirement_candidate') }} c left join {{ ref('fct_model_response') }} r using(response_id) where r.response_id is null
union all select r.response_id from {{ ref('fct_model_response') }} r left join {{ ref('dim_model_run') }} m using(model_run_id) where m.model_run_id is null
