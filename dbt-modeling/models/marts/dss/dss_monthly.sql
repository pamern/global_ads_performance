{{ config(alias='DssMonthly', tags=['dss']) }}

-- Grain: one platform x calendar month in 2024, following the DSS POC.
-- Keep invalid measures visible; data tests reject them rather than impute/drop.
with monthly as (
    select
        case platform
            when 'Google Ads' then 'Google'
            when 'Meta Ads' then 'Meta'
            when 'TikTok Ads' then 'TikTok'
        end as "Platform",
        date_trunc('month', date)::date as "Month",
        sum(ad_spend) as "AdSpend",
        sum(revenue) as "Revenue",
        sum(impressions) as "Impressions",
        sum(conversions) as "Conversions"
    from {{ ref('int_ads_performance') }}
    where date >= date '2024-01-01' and date < date '2025-01-01'
      and platform in ('Google Ads', 'Meta Ads', 'TikTok Ads')
    group by 1, 2
)
select
    *,
    "Revenue"::numeric / nullif("AdSpend", 0) as "RevenuePerDollar",
    "Impressions"::numeric / nullif("AdSpend", 0) as "ImpressionsPerDollar",
    "Conversions"::numeric / nullif("AdSpend", 0) as "ConversionsPerDollar"
from monthly
