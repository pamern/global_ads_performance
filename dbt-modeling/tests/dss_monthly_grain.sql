{{ config(tags=['dss']) }}

-- A full outer join also reports missing states and unexpected platform/months.
with expected as (
    select p.platform, m.month::date as month
    from (values ('Google'), ('Meta'), ('TikTok')) as p(platform)
    cross join generate_series(date '2024-01-01', date '2024-12-01', interval '1 month') as m(month)
), actual as (
    select "Platform" as platform, "Month" as month, count(*) as row_count
    from {{ ref('dss_monthly') }}
    group by 1, 2
)
select e.platform as expected_platform, e.month as expected_month, a.*
from expected e
full outer join actual a on a.platform = e.platform and a.month = e.month
where e.platform is null or a.row_count is distinct from 1::bigint
