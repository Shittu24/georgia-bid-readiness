select * from {{ source('closeout_reporting','current_requirement_assertions') }}
