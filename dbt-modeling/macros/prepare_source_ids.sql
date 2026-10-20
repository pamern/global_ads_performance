{% macro prepare_source_ids() %}
{% if execute %}
  {% if target.name == 'local' and target.host not in ['127.0.0.1', 'localhost', '::1'] %}
    {{ exceptions.raise_compiler_error('local target must use a loopback host') }}
  {% endif %}
  {% if target.name == 'dev' and env_var('NEXORA_DEV_VERIFIED', '') != target.host ~ '/' ~ target.dbname %}
    {{ exceptions.raise_compiler_error('Verify dev database/schema/permissions first; set NEXORA_DEV_VERIFIED=host/database') }}
  {% endif %}
  {% set schema = 'mapping' %}
  {% do run_query('create schema if not exists ' ~ adapter.quote(schema)) %}
  {% set ddl %}
    create table if not exists {{ adapter.quote(schema) }}.source_rows (
      source_row_id bigint generated always as identity primary key,
      payload jsonb not null unique
    )
  {% endset %}
  {% do run_query(ddl) %}
  {% set insert %}
    insert into {{ adapter.quote(schema) }}.source_rows (payload)
    select distinct to_jsonb(r) as payload from {{ source('raw', 'global_ads_performance') }} r
    where not exists (
      select 1 from {{ adapter.quote(schema) }}.source_rows m
      where m.payload = to_jsonb(r)
    )
    order by payload
    on conflict (payload) do nothing
  {% endset %}
  {% do run_query(insert) %}
{% endif %}
select 1
{% endmacro %}
