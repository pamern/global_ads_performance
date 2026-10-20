{{ config(severity='warn') }}
select source_row_id, source_ctr, ctr, abs(source_ctr - ctr) as difference
from {{ ref('int_ads_performance') }}
where ctr is not null and abs(source_ctr - ctr) > 0.00005
