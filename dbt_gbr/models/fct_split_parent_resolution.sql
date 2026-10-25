select * from {{ source('closeout_reporting','split_parent_resolution') }}
