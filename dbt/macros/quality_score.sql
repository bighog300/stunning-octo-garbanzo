{% macro quality_score() %}
    least(100, greatest(0,
        case when artist_name is not null then 20 else 0 end +
        case when artwork_title is not null then 20 else 0 end +
        case when year_start is not null then 10 else 0 end +
        case when medium_text is not null then 10 else 0 end +
        case when dimensions_text is not null then 10 else 0 end +
        case when image_url is not null then 10 else 0 end +
        case when source_url is not null then 10 else 0 end +
        case when description is not null then 10 else 0 end
    ))
{% endmacro %}
