select * from {{ ref('int_ads_performance') }}
where (impressions = 0 and ctr is not null) or (impressions <> 0 and ctr is distinct from clicks::numeric / nullif(impressions, 0))
   or (clicks = 0 and cpc is not null) or (clicks <> 0 and cpc is distinct from ad_spend::numeric / nullif(clicks, 0))
   or (conversions = 0 and cpa is not null) or (conversions <> 0 and cpa is distinct from ad_spend::numeric / nullif(conversions, 0))
   or (clicks = 0 and conversion_rate is not null) or (clicks <> 0 and conversion_rate is distinct from conversions::numeric / nullif(clicks, 0))
   or (ad_spend = 0 and roas is not null) or (ad_spend <> 0 and roas is distinct from revenue::numeric / nullif(ad_spend, 0))
