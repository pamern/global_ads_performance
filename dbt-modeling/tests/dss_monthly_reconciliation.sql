{{ config(tags=['dss']) }}

-- Independent aggregation from the existing BI star schema, exact NUMERIC comparison.
with expected as (
    select
        replace(p."Platform", ' Ads', '') as platform,
        date_trunc('month', d."Date")::date as month,
        sum(f."AdSpend") as spend,
        sum(f."Revenue") as revenue,
        sum(f."Impressions") as impressions,
        sum(f."Conversions") as conversions
    from {{ ref('fct_ad_performance') }} f
    join {{ ref('dim_date') }} d on d."DateKey" = f."DateKey"
    join {{ ref('dim_platform') }} p on p."PlatformKey" = f."PlatformKey"
    where d."Date" >= date '2024-01-01' and d."Date" < date '2025-01-01'
      and p."Platform" in ('Google Ads', 'Meta Ads', 'TikTok Ads')
    group by 1, 2
)
select
    e.platform as expected_platform, e.month as expected_month,
    e.spend as expected_spend, e.revenue as expected_revenue,
    e.impressions as expected_impressions, e.conversions as expected_conversions,
    a.*
from expected e
full outer join {{ ref('dss_monthly') }} a
    on a."Platform" = e.platform and a."Month" = e.month
where e.platform is null or a."Platform" is null
   or a."AdSpend" is distinct from e.spend
   or a."Revenue" is distinct from e.revenue
   or a."Impressions" is distinct from e.impressions
   or a."Conversions" is distinct from e.conversions
