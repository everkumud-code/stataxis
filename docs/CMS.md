# Website CMS: Services and Blog

The public website (www.stataxis.org) has two sections written in the workspace instead of in files: **Services** and the **Blog** (Insights). Both are under the admin menu group **Website**. Administrators only.

## What is where

| Part | File |
|---|---|
| Tables `stx_services`, `stx_service_revisions`, `stx_posts`, `stx_post_revisions` | `collector/storage.py` |
| Services logic, search checks, HTML, sitemap, robots, llms.txt | `api/services_cms.py` |
| The 11 starter services (editable, written once) | `api/services_seed.py` |
| Blog logic, text format, HTML, Insights list | `api/blog_cms.py` |
| Editing routes `/api/v1/cms/...` and public pages | `api/services_http.py`, wired in `web.py` |
| Admin screens "Website services" and "Website blog" | `dashboard/cms.js` |
| Menu "Services" with drop-down, footer link, styles | `dashboard/site.js`, `dashboard/tech.css` |
| Tests | `tests/test_services.py`, `tests/test_blog_cms.py` |

## Public addresses (written by the server, plain HTML)

`/services`, `/services/<address>`, `/blog/<address>` (CMS articles only), `/sitemap.xml`, `/robots.txt`, `/llms.txt`, and the list `GET /api/v1/public/services` that fills the menu drop-down. The six articles that were built into the site as files are **never touched**: they are served from their files, listed read-only in the editor, and their addresses cannot be taken by a new article.

## Search side (each page)

Title, description, keywords, canonical address (own address unless set, and only on stataxis.org), Open Graph and Twitter tags, `robots` meta (a page can be kept out of search results), structured data (Service, FAQPage, BreadcrumbList, CollectionPage/ItemList, Organization for services; Article and BreadcrumbList for blog), breadcrumbs, internal links between related pages, ETag with 304, real 404 for an unknown address, 301 for an address that was changed, 410 for one that was deleted. The sitemap lists only live, indexable pages; `robots.txt` answers even when the database is down. The editor shows a live Google preview and a checklist (title and description length, main keyword placement, words, headings, links, duplicates).

## Rules

- Every change is kept whole in the revision table; an earlier version comes back as a **draft**. A deleted service or article can be brought back at the same address.
- Starter services are written once (flag `services_seeded` in `stx_settings`); a deleted starter does not return unless "Add back any starter service that is missing" is pressed, and an edited one is never overwritten.
- A scheduled article goes live at its time by itself (the server compares the time on each request; pages are kept for 30 seconds).
- The article text format is safe by construction: everything is escaped first, only `##`, `###`, lists, quotes, `**bold**`, `*italic*` and `[words](address)` are understood, and an address must start with `https://`, `http://`, `mailto:` or a single `/`.
- Services never promise data that does not exist: platform coverage follows the published roadmap (YouTube today, Instagram and Facebook from January 2027, X during 2027, connected TV from July 2027).
