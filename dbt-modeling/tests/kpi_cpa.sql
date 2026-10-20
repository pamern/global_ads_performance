select source_row_id, source_cpa, cpa, abs(source_cpa - cpa) as difference
from {{ ref('int_ads_performance') }}
where cpa is not null and abs(source_cpa - cpa) > 0.005
