select
    m.source_row_id,
    r.date::date as date,
    r."platform"::text as platform,
    r."campaign_type"::text as campaign_type,
    r."industry"::text as industry,
    r."country"::text as country,
    r."impressions"::bigint as impressions,
    r."clicks"::bigint as clicks,
    r."CTR"::numeric as source_ctr,
    r."CPC"::numeric as source_cpc,
    r."ad_spend"::numeric as ad_spend,
    r."conversions"::bigint as conversions,
    r."CPA"::numeric as source_cpa,
    r."revenue"::numeric as revenue,
    r."ROAS"::numeric as source_roas
from {{ source('raw', 'global_ads_performance') }} r
join mapping.source_rows m on m.payload = to_jsonb(r)
