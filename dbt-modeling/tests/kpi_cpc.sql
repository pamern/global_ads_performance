select source_row_id, source_cpc, cpc, abs(source_cpc - cpc) as difference
from {{ ref('int_ads_performance') }}
where cpc is not null and abs(source_cpc - cpc) > 0.005
