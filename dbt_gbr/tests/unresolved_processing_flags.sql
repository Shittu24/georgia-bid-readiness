select page_extraction_key from {{ ref('fct_page_extraction') }} where status='failed' or unresolved_flag
