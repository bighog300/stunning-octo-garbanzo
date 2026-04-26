# AGENTS.md

Use the full AGENTS.md generated in canvas as the source of truth.

Minimum rule for Codex:

1. Follow `/docs`.
2. Build the MVP vertical slice first.
3. Do not add extra spiders before `metmuseum_artworks` works.
4. Scrapy writes only to `raw`.
5. dbt writes only to `analytics`.
6. Artio writes only to `app`.
7. Validate each phase before continuing.
