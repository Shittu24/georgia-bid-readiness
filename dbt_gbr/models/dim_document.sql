select document_id,solicitation_id,document_type,amendment_number,created_at from {{ source('core','documents') }}
