with counts as (
select (select count(*) from {{ source('raw', 'global_ads_performance') }}) r,
(select count(*) from {{ ref('stg_ads_performance') }}) s,
(select count(*) from {{ ref('int_ads_performance') }}) i,
(select count(*) from {{ ref('fct_ad_performance') }}) f
) select * from counts where r <> s or r <> i or r <> f
