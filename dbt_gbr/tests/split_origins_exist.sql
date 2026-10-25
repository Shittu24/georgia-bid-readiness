select s.split_id from {{ source('core','split_requirements') }} s where not exists(select 1 from core.split_requirement_origins o where o.split_id=s.split_id)
