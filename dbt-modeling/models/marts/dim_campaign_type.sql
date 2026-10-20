{{ config(alias='DimCampaignType') }}

select campaign_type_key::integer as "CampaignTypeKey", campaign_type as "CampaignType"
from {{ ref('map_campaign_type') }}
