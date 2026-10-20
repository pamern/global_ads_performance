{{ config(alias='DimCountry') }}

select country_key::integer as "CountryKey", country as "Country"
from {{ ref('map_country') }}
