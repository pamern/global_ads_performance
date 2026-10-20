select source_row_id, source_roas, roas, abs(source_roas - roas) as difference
from {{ ref('int_ads_performance') }}
where roas is not null and abs(source_roas - roas) > 0.005
