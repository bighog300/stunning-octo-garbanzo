{% macro clean_text(column_name) %}
    nullif(trim(regexp_replace({{ column_name }}, '\s+', ' ', 'g')), '')
{% endmacro %}
