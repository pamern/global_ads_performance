select to_jsonb(r) as payload, count(*)
from {{ source('raw', 'global_ads_performance') }} r
group by to_jsonb(r) having count(*) > 1
