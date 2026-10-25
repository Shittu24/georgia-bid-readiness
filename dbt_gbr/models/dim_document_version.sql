select md5(document_id || ':' || sha256) as document_version_key,document_id,sha256,local_path,size_bytes,page_count,created_at from {{ source('core','document_versions') }}
