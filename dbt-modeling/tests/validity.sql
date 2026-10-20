select * from {{ ref('stg_ads_performance') }}
where impressions < 0 or clicks < 0 or conversions < 0 or ad_spend < 0 or revenue < 0
   or clicks > impressions or source_ctr not between 0 and 1
   or source_cpc < 0 or source_cpa < 0 or source_roas < 0
   or (clicks = 0 and (conversions > 0 or source_cpc > 0))
   or (conversions = 0 and source_cpa > 0)
   or (ad_spend = 0 and source_roas > 0)
   or ad_spend::text in ('NaN', 'Infinity', '-Infinity')
   or revenue::text in ('NaN', 'Infinity', '-Infinity')
