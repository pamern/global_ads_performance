select s.source_row_id, f."FactId"
from {{ ref('stg_ads_performance') }} s
full join {{ ref('fct_ad_performance') }} f on f."FactId" = s.source_row_id
where s.source_row_id is null or f."FactId" is null or s.impressions is distinct from f."Impressions" or s.clicks is distinct from f."Clicks" or s.conversions is distinct from f."Conversions" or s.ad_spend is distinct from f."AdSpend" or s.revenue is distinct from f."Revenue"
