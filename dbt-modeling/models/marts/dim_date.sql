{{ config(alias='DimDate') }}

with dates as (
    select generate_series(min(date), max(date), interval '1 day')::date as date
    from {{ ref('stg_ads_performance') }}
)
select
    to_char(date, 'YYYYMMDD')::integer as "DateKey",
    date as "Date",
    extract(day from date)::integer as "Day",
    extract(month from date)::integer as "Month",
    to_char(date, 'FMMonth') as "MonthName",
    extract(quarter from date)::integer as "Quarter",
    extract(year from date)::integer as "Year"
from dates
