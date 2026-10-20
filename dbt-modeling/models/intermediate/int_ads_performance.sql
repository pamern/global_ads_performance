select
    s.*,
    clicks::numeric / nullif(impressions, 0) as ctr,
    ad_spend::numeric / nullif(clicks, 0) as cpc,
    ad_spend::numeric / nullif(conversions, 0) as cpa,
    conversions::numeric / nullif(clicks, 0) as conversion_rate,
    revenue::numeric / nullif(ad_spend, 0) as roas
from {{ ref('stg_ads_performance') }} s
