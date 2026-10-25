select * from {{ source('reporting','split_requirement_status') }}
