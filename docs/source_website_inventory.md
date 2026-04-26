# Artio Source Website Inventory

## 1. Purpose

This document defines the initial set of art-related websites to be crawled by the Artio data pipeline. It captures structure, risks, and extraction opportunities for each source.

This document is critical because it directly determines:

- What data enters the system
- How complex the spiders will be
- Legal/compliance constraints
- Data quality expectations

---

## 2. How to Use This Document

Each source should be reviewed and approved before building a Scrapy spider.

For each website:

1. Confirm it is allowed or safe to crawl
2. Identify the correct entry points (listing pages)
3. Identify data fields available
4. Assess difficulty (HTML vs JS-heavy)
5. Define crawl frequency

---

## 3. Source Inventory (MVP Set)

### 3.1 Artsy

**Base URL** [https://www.artsy.net](https://www.artsy.net)

**Type** Marketplace / gallery aggregator

**Target pages**

- Artist pages
- Artwork listings

**Example URLs**

- [https://www.artsy.net/artwork](https://www.artsy.net/artwork)
- [https://www.artsy.net/artist](https://www.artsy.net/artist)

**Data available**

- Artist name
- Artwork title
- Year
- Medium
- Dimensions
- Price (sometimes hidden)
- Gallery
- Image URL

**Pagination**

- Infinite scroll / API-driven

**Rendering**

- JS-heavy (requires API or headless browser fallback)

**Difficulty** High

**Anti-bot risk** High

**Crawl frequency** Weekly

**Notes**

- Prefer API endpoints if discoverable
- Avoid aggressive crawling

---

### 3.2 The Metropolitan Museum of Art

**Base URL** [https://www.metmuseum.org](https://www.metmuseum.org)

**Type** Museum collection

**Target pages**

- Collection search
- Artwork detail pages

**Example URLs**

- [https://www.metmuseum.org/art/collection](https://www.metmuseum.org/art/collection)

**Data available**

- Artist name
- Artwork title
- Date
- Medium
- Dimensions
- Collection department
- Image URL

**Pagination**

- Query-based pagination

**Rendering**

- Mostly server-rendered

**Difficulty** Low

**Anti-bot risk** Low

**Crawl frequency** Monthly

**Notes**

- Good first target for MVP
- Structured and consistent

---

### 3.3 Tate

**Base URL** [https://www.tate.org.uk](https://www.tate.org.uk)

**Type** Museum collection

**Target pages**

- Artists
- Artworks

**Example URLs**

- [https://www.tate.org.uk/art/artworks](https://www.tate.org.uk/art/artworks)

**Data available**

- Artist name
- Artwork title
- Date
- Medium
- Dimensions
- Collection
- Image URL

**Pagination**

- Page-based

**Rendering**

- Server-rendered

**Difficulty** Low

**Anti-bot risk** Low

**Crawl frequency** Monthly

---

### 3.4 Saatchi Art

**Base URL** [https://www.saatchiart.com](https://www.saatchiart.com)

**Type** Online gallery / marketplace

**Target pages**

- Artwork listings

**Example URLs**

- [https://www.saatchiart.com/paintings](https://www.saatchiart.com/paintings)

**Data available**

- Artist name
- Artwork title
- Price
- Medium
- Dimensions
- Image URL

**Pagination**

- Page-based + filters

**Rendering**

- Mixed (some JS)

**Difficulty** Medium

**Anti-bot risk** Medium

**Crawl frequency** Weekly

---

### 3.5 MutualArt

**Base URL** [https://www.mutualart.com](https://www.mutualart.com)

**Type** Art market data / auction aggregator

**Target pages**

- Artist pages
- Auction results

**Data available**

- Artist
- Artwork
- Auction price
- Date

**Pagination**

- Page-based

**Rendering**

- Mixed / partially gated

**Difficulty** High

**Anti-bot risk** High

**Crawl frequency** Weekly

---

## 4. Field Coverage Matrix

| Field         | Artsy | Met | Tate | Saatchi | MutualArt |
| ------------- | ----- | --- | ---- | ------- | --------- |
| Artist        | ✓     | ✓   | ✓    | ✓       | ✓         |
| Artwork Title | ✓     | ✓   | ✓    | ✓       | ✓         |
| Year          | ✓     | ✓   | ✓    | ✓       | ✓         |
| Medium        | ✓     | ✓   | ✓    | ✓       | ✓         |
| Dimensions    | ✓     | ✓   | ✓    | ✓       | ✓         |
| Price         | \~    | ✗   | ✗    | ✓       | ✓         |
| Image URL     | ✓     | ✓   | ✓    | ✓       | ✓         |
| Source URL    | ✓     | ✓   | ✓    | ✓       | ✓         |

---

## 5. MVP Recommendation

Start with:

```text
The Metropolitan Museum of Art
```

Reasons:

- Stable HTML structure
- Low anti-bot risk
- High-quality metadata
- Easier Scrapy implementation

Then expand to:

```text
Tate → Saatchi Art → Artsy
```

---

## 6. Risk Classification

| Risk Level | Description                               |
| ---------- | ----------------------------------------- |
| Low        | Server-rendered, open access              |
| Medium     | Some JS or pagination complexity          |
| High       | JS-heavy, API hidden, anti-bot protection |

---

## 7. Approval Checklist (per source)

Before building a spider:

```text
[ ] robots.txt reviewed
[ ] terms of service reviewed
[ ] crawl rate defined
[ ] entry URLs identified
[ ] pagination understood
[ ] required fields confirmed
[ ] anti-bot risk assessed
[ ] storage policy decided (images vs URLs)
```

---

## 8. Next Step

Next document:

```text
Data Schema Specification
```

