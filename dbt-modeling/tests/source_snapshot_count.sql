select count(*) as actual_count from {{ source('raw', 'global_ads_performance') }} having count(*) != {{ var('expected_source_rows', 1800) }}
