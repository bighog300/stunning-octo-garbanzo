# Artio Crawling & Compliance Policy

## 1. Purpose

This document defines the legal, ethical, and operational rules for crawling art-related websites in the Artio pipeline.

Its goal is to ensure:

- Responsible data collection
- Compliance with website policies
- Respect for intellectual property
- Reduced risk of blocking or legal issues

---

## 2. Core Principles

All crawling must follow these principles:

```text
Respect website rules
Minimize server load
Preserve attribution
Avoid misuse of copyrighted content
Be transparent when possible
```

---

## 3. Allowed Data Types

The pipeline is designed to collect:

```text
Artwork metadata (title, artist, year)
Descriptive fields (medium, dimensions)
Publicly visible prices (if available)
Public image URLs (not files)
Source URLs
```

Not allowed (MVP):

```text
Bulk image downloading
Private or gated data
User accounts or personal data
Circumventing paywalls or authentication
```

---

## 4. robots.txt Policy

Before crawling any site:

```text
[ ] Check robots.txt
[ ] Confirm allowed paths
[ ] Respect disallowed paths
```

Default rule:

```text
If robots.txt disallows crawling → do NOT crawl
```

---

## 5. Terms of Service (ToS)

Each source must be reviewed:

```text
[ ] Terms of service checked
[ ] Data usage restrictions noted
[ ] Commercial use restrictions noted
```

If ToS explicitly prohibits scraping:

```text
Do NOT crawl unless legal review is completed
```

---

## 6. Rate Limiting

Default crawl limits:

```text
1–2 requests per second
Concurrent requests ≤ 2 per domain
```

High-risk sites:

```text
1 request every 3–5 seconds
```

Goal:

```text
Avoid impacting site performance
Avoid triggering anti-bot systems
```

---

## 7. User Agent Policy

Use identifiable user agent:

```text
ArtioResearchBot/0.1 (+contact-email-or-site)
```

Do not impersonate browsers deceptively.

---

## 8. Anti-Bot Measures

The system must NOT:

```text
Bypass CAPTCHA systems
Use credential stuffing
Exploit vulnerabilities
Use aggressive proxy evasion without approval
```

If blocked:

```text
Reduce crawl rate
Pause crawling
Review compliance
```

---

## 9. Image Policy

MVP rules:

```text
Store image URLs only
Do NOT download images in bulk
Do NOT host images without permission
```

Future rules (if needed):

```text
Check licensing
Store only permitted images
Respect copyright restrictions
```

---

## 10. Attribution Requirements

Every record must include:

```text
source_name
source_url
```

Artio UI should display:

```text
Source attribution
Link to original page
```

---

## 11. Data Retention

Rules:

```text
Raw data is stored for traceability
Records can be removed upon request
Rejected or invalid data may be retained internally
```

---

## 12. Takedown Policy

If a source requests removal:

```text
1. Identify affected records
2. Remove or disable records
3. Stop crawling affected paths
4. Log request and action taken
```

---

## 13. Source Approval Process

Before adding a new source:

```text
[ ] Added to Source Inventory
[ ] robots.txt reviewed
[ ] ToS reviewed
[ ] Risk level assigned
[ ] Crawl frequency defined
[ ] Data fields confirmed
[ ] Approval recorded
```

---

## 14. Risk Levels

| Level | Description |
|------|------------|
| Low | Open data, public institutions |
| Medium | Some restrictions or JS complexity |
| High | Marketplace, API-gated, anti-bot systems |

---

## 15. Compliance Logging

Track per source:

```text
approval status
last review date
robots.txt status
ToS notes
crawl limits
```

---

## 16. Prohibited Actions

The system must never:

```text
Collect personal data
Scrape login-protected areas
Circumvent access controls
Sell or redistribute copyrighted content improperly
Overload servers
```

---

## 17. Incident Response

If an issue occurs:

```text
Stop crawling immediately
Investigate logs
Identify affected sources
Apply fixes
Update policy if needed
```

---

## 18. MVP Compliance Scope

For MVP:

```text
Use low-risk sources (museums)
Avoid marketplaces initially
Store metadata only
Respect robots.txt strictly
```

---

## 19. Acceptance Criteria

Compliance is met when:

```text
[ ] robots.txt respected
[ ] ToS reviewed
[ ] Crawl rates enforced
[ ] Attribution stored
[ ] No prohibited data collected
```

---

## 20. Ongoing Review

Review policy periodically:

```text
Monthly for active sources
Immediately after incidents
Before adding new sources
```

---

## 21. Final Note

This policy protects:

```text
The Artio platform
Data sources
Users
Long-term sustainability of the pipeline
```

