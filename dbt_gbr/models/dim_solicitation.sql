select solicitation_id,agency_name,solicitation_number,title,source_page_url,created_at from {{ source('core','solicitations') }}
