{{ config(alias='FctAdPerformance') }}

select
    s.source_row_id as "FactId",
    d."DateKey",
    platform."PlatformKey",
    campaign_type."CampaignTypeKey",
    industry."IndustryKey",
    country."CountryKey",
    s.impressions as "Impressions",
    s.clicks as "Clicks",
    s.ad_spend as "AdSpend",
    s.conversions as "Conversions",
    s.revenue as "Revenue"
from {{ ref('int_ads_performance') }} s
left join {{ ref('dim_date') }} d on d."Date" = s.date
left join {{ ref('dim_platform') }} platform on platform."Platform" = s.platform
left join {{ ref('dim_campaign_type') }} campaign_type on campaign_type."CampaignType" = s.campaign_type
left join {{ ref('dim_industry') }} industry on industry."Industry" = s.industry
left join {{ ref('dim_country') }} country on country."Country" = s.country
