{{ config(alias='DimPlatform') }}

select platform_key::integer as "PlatformKey", platform as "Platform"
from {{ ref('map_platform') }}
