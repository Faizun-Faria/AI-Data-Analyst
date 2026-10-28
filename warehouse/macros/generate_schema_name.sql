-- Use each folder's schema name as is (staging, quality, marts, reference) instead of
-- dbt's default of prefixing it with the target schema (main_staging, ...).
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name or target.schema }}
{%- endmacro %}
