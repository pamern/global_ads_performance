{{ config(alias='DimIndustry') }}

select industry_key::integer as "IndustryKey", industry as "Industry"
from {{ ref('map_industry') }}
