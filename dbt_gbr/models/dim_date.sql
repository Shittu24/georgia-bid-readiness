with dates as (
select started_at::date as d from {{ source('core','pipeline_runs') }} where started_at is not null
union all select reviewed_at::date from {{ source('core','requirement_reviews') }}
), bounds as(select coalesce(min(d),date '2026-01-01') lo,coalesce(max(d),date '2026-01-01') hi from dates)
select d::date date_day,extract(year from d)::int as calendar_year,extract(quarter from d)::int as calendar_quarter,
extract(month from d)::int as calendar_month,extract(isodow from d)::int iso_weekday
from bounds cross join lateral generate_series(lo::timestamp,hi::timestamp,interval '1 day') d
