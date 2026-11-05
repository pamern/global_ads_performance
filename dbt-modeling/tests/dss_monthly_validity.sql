{{ config(tags=['dss']) }}

-- Check source rows too: SUM must not hide NULL/negative/invalid measures.
select 'source' as layer, platform, date as month
from {{ ref('int_ads_performance') }}
where date >= date '2024-01-01' and date < date '2025-01-01'
  and (
      platform is null or platform not in ('Google Ads', 'Meta Ads', 'TikTok Ads')
      or ad_spend is null or revenue is null or impressions is null or conversions is null
      or ad_spend < 0 or revenue < 0 or impressions < 0 or conversions < 0
      or ad_spend::text in ('NaN', 'Infinity', '-Infinity')
      or revenue::text in ('NaN', 'Infinity', '-Infinity')
  )
union all
select 'mart', "Platform", "Month"
from {{ ref('dss_monthly') }}
where "AdSpend" <= 0 or "Revenue" < 0 or "Impressions" < 0 or "Conversions" < 0
   or "AdSpend"::text in ('NaN', 'Infinity', '-Infinity')
   or "Revenue"::text in ('NaN', 'Infinity', '-Infinity')
   or "RevenuePerDollar"::text in ('NaN', 'Infinity', '-Infinity')
   or "ImpressionsPerDollar"::text in ('NaN', 'Infinity', '-Infinity')
   or "ConversionsPerDollar"::text in ('NaN', 'Infinity', '-Infinity')
   or "RevenuePerDollar" is distinct from "Revenue"::numeric / nullif("AdSpend", 0)
   or "ImpressionsPerDollar" is distinct from "Impressions"::numeric / nullif("AdSpend", 0)
   or "ConversionsPerDollar" is distinct from "Conversions"::numeric / nullif("AdSpend", 0)
