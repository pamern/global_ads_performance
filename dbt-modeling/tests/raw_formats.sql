select to_jsonb(r) as payload
from {{ source('raw', 'global_ads_performance') }} r
where date !~ '^\d{4}-\d{2}-\d{2}$'
   or to_char(date::date, 'YYYY-MM-DD') <> date
   or impressions !~ '^\d+$' or clicks !~ '^\d+$' or conversions !~ '^\d+$'
   or ad_spend !~ '^\d+(\.\d{1,2})?$' or revenue !~ '^\d+(\.\d{1,2})?$'
   or "CTR" !~ '^\d+(\.\d{1,4})?$'
   or "CPC" !~ '^\d+(\.\d{1,2})?$'
   or "CPA" !~ '^\d+(\.\d{1,2})?$'
   or "ROAS" !~ '^\d+(\.\d{1,2})?$'
   or btrim(platform) = '' or btrim(campaign_type) = ''
   or btrim(industry) = '' or btrim(country) = ''
