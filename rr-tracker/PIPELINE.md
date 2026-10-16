# Top Accounting R&R Tracker: data pipeline (stages 1-2 prototype)

Run date: 2026-10-15. Every number below comes from the logs in `logs/`. Nothing in `data/` is sample or demo data. Every R&R candidate carries the URL it was found on and a verbatim snippet.

## Layout

```
pipeline/01_cohort.py         OpenAlex: journals -> works -> author cohort
pipeline/02_homepages.py      public ORCID API: researcher-urls for every cohort ORCID
pipeline/02b_institutional.py institution homepage -> sitemap -> profile page (accounting-5 only, top 40 institutions)
pipeline/03_scan.py           crawl candidate pages, extract R&R mentions
data/                         outputs (CSV/JSON)
logs/                         one log per step
```

Run order (full run): `python3 pipeline/01_cohort.py && python3 pipeline/02_homepages.py && python3 pipeline/02c_directories.py && python3 pipeline/03_scan.py 0 && python3 pipeline/04_staleness.py`, then the independent review writes `data/rr_review.json`, then `python3 pipeline/05_publish.py && python3 ../build.py`.

## Step 1: cohort (`01_cohort.py`)

The script resolves each journal by ISSN through `/sources?filter=issn:` and asserts that the display name matches exactly:

| Code | ISSN | OpenAlex source | Articles 2021-2026 | Authors with >=1 article |
|---|---|---|---|---|
| JAE | 0165-4101 | S62142384 | 287 | 580 |
| JAR | 0021-8456 | S111116695 | 266 | 565 |
| TAR | 0001-4826 | S160506855 | 590 | 1,112 |
| CAR | 0823-9150 | S65924262 | 461 | 1,036 |
| RAST | 1380-6653 | S11853582 | 375 | 857 |
| MS | 0025-1909 | S33323087 | 2,417 | 5,173 |

- Works filter: `primary_location.source.id`, `publication_year:2021-2026`, `type:article`. The `article` type in OpenAlex includes journal "Discussion of ..." pieces, so discussants are in the cohort. It excludes paratext, editorials, errata and retractions; for JAE those are 36, 31, 2 and 1 items.
- There are **7,470 unique OpenAlex author ids**. The **accounting-5 cohort** (at least one article in JAE, JAR, TAR, CAR or RAST) has **2,806** of them, and **4,664** are Management Science only. The flag is `acc5_flag` in `cohort_authors.csv`.
- **6,800** authors have an ORCID in OpenAlex, 2,471 of them in the accounting-5 cohort.
- Institutions come from the OpenAlex author record (`last_known_institutions`), with a fallback to the institution on the author's latest paper in the window. 1,065 institutions were resolved for the accounting-5 cohort, and 1,057 of them have a `homepage_url`.
- The run made 203 OpenAlex requests and took 134 s.
- **OpenAlex change (2026):** without an API key, an IP gets about 1,000 requests a day, and cursor paging past page 1 returns HTTP 401 ("API key required for cursor paging"). The script therefore uses `page=` paging, which works because every journal has fewer than 10,000 works. If `OPENALEX_API_KEY` is set, it uses cursors instead.

Outputs: `data/journal_sources.csv`, `data/cohort_works.csv` (one row per work and authorship), `data/cohort_authors.csv`, `data/institutions.csv`.

## Step 2a: ORCID homepages (`02_homepages.py`)

The script makes one `GET pub.orcid.org/v3.0/{orcid}/person` per distinct ORCID. The person record embeds `researcher-urls`. No search engines are used.

- 6,758 distinct ORCIDs were queried, all of them for the full cohort. 6,756 returned HTTP 200 and 2 returned HTTP 409 (deprecated or locked records). The run took 725 s (12 minutes) with 6 threads.

| Cohort | Authors | With ORCID | With >=1 ORCID URL |
|---|---|---|---|
| Full (6 journals) | 7,470 | 6,800 (91.0%) | 1,491 (20.0%) |
| Accounting-5 | 2,806 | 2,471 (88.1%) | 407 (14.5%) |
| MS only | 4,664 | 4,329 (92.8%) | 1,084 (23.2%) |

- Name check: the ORCID family name must appear in the OpenAlex display name. Of the 1,995 URL rows, 55 fail this check (`name_match=no`), which suggests a wrong ORCID link in OpenAlex. The scan does not use those rows.
- Not every URL is a personal site. For accounting-5, 117 of the 552 URL rows point to LinkedIn, Google Scholar, SSRN, ResearchGate, Twitter, GitHub and similar sites, and step 3 skips them. That leaves 378 accounting-5 authors with at least one crawlable URL.

Output: `data/homepages_orcid.csv` (it records the url, ORCID url-name and `source=orcid:researcher-urls` for every row) and `data/orcid_person_cache.jsonl`.

## Step 2b: institutional profile route (`02b_institutional.py`, accounting-5 only)

The route runs: OpenAlex last-known institution, then the institution `homepage_url`, then robots.txt `Sitemap:` lines (or `/sitemap.xml`), then bounded expansion of sitemap indexes (at most 80 sitemaps or 60 MB per institution). It keeps sitemap URLs whose path contains a name slug (`first-last`, `last-first`, `firstlast`, `first_last`, `first.last`). It then fetches the candidate page, after checking robots.txt, and keeps it only if the `<title>` contains both the first-name and last-name tokens.

It was tested on the 40 institutions with the most accounting-5 authors, which covers 815 of the 2,806 authors (runtime 104 s):
- 13 of the 40 have no reachable sitemap.
- Most of the 27 that do have one publish sitemaps for the main university host only. Business schools live on subdomains (for example `gies.illinois.edu` or `mccombs.utexas.edu`), so faculty pages are not in the sitemap.
- 22 authors matched a page with their name in the title. After keeping only profile or directory paths (step 3 drops news stories that merely mention the person), **14 authors** remain, almost all at Erasmus (`eur.nl/people/...`) and Boston College. 11 of those 14 had no ORCID URL.
- **Incremental coverage, accounting-5:** ORCID only gives 407 of 2,806 (14.5%). ORCID plus this route gives 418 of 2,806 (14.9%). Among the 815 authors at the 40 tested institutions, coverage rises from 115 (ORCID) to 126.
- **Verdict:** the route is deterministic but low-yield. A better institutional route is a curated, version-controlled list of accounting-department faculty-directory URLs, about 150 schools cover most of the cohort, parsed per school. That has not been built yet.

**SSRN author pages are infeasible.** SSRN's robots.txt permits `*` with `Crawl-Delay: 5`, but `papers.ssrn.com/sol3/cf_dev/AbsByAuth.cfm` returned HTTP 403 to our User-Agent (bot protection). There is also no deterministic OpenAlex-to-SSRN author-id link, so the route was not pursued.

Outputs: `data/homepages_institutional.csv` (it records `source=institution-sitemap:<homepage>` and the page title) and `data/institution_sitemap_status.csv`.

## Step 3: R&R scan prototype (`03_scan.py`)

- **Sample:** 150 of the 378 accounting-5 authors with a crawlable URL, drawn at random with a fixed seed (20261015). They are not hand-picked.
- **Crawl:** each start URL (at most 3 per author), plus at most 2 same-host links whose anchor text or path matches `research|papers|working|cv|vita`. PDFs are followed only when the file name matches `cv|vita|curriculum`, and their text is extracted with `pdftotext`. The crawler honours robots.txt (`urllib.robotparser`), waits at least 1 s between requests to the same host, uses a 15 s timeout, and sends the UA `shibaoliu.github.io RR tracker (contact: tanglin817@gmail.com)`.
- **Match:** a status phrase (`revise and/& resubmit`, `R&R`, `revision requested`, `second/2nd round`, `resubmitted`) must be syntactically attached to a journal name or abbreviation (JAE, JAR, TAR, CAR, RAST/RAS, MS, or the full names). Attached means one of these:
  - the journal follows the phrase, separated only by punctuation or "at/in/the" ("R&R at The Accounting Review", "Revise and resubmit, Contemporary Accounting Research"), or
  - the journal immediately precedes the phrase ("Management Science, R&R").

  The task asked for proximity within about 200 characters, and the first prototype run used exactly that rule. It produced 17 candidates, 5 of them wrong: "R&R at Journal of Financial Economics" was assigned to a neighbouring "Accepted at Management Science", "European Accounting Review" matched "Accounting Review", and "Financial Management" was picked up from a neighbouring line. All 5 disappeared under the attachment rule, and no genuine candidate was lost. "Accounting Review" now also has negative look-behinds for European, British, Asian and other prefixes.
- **Title extraction:**
  - **high** confidence: a quoted string, or an emphasised (bold, italic or link) segment before the phrase.
  - **low** confidence: the text before "(with ...", the text before the phrase, or the preceding line.
  - When nothing is found, the title is recorded as `unknown`.
- **Staleness check:** the extracted title is fuzzy-matched (difflib ratio of at least 0.85) against the six journals' published 2021-2026 articles in `cohort_works.csv`. A match is recorded in `already_published_match`.
- **Other flags:** `flag_referee_context` and `flag_published_context`.

**Results (logs/03_scan.log, 74 s):**
- 358 fetches: HTTP 200 for 258 (249 HTML, 9 PDF), 403 for 71, 404 for 15, 401 for 3, 7 robots-disallowed, 4 errors or timeouts.
- 125 of the 150 authors had at least one page fetched successfully.
- **12 candidates from 8 authors:** TAR 3, CAR 2, JAR 1, MS 6, JAE 0, RAST 0.
- 8 candidates have high-confidence titles, and 1 is flagged as already published (Cong et al., "Crypto Value, Factor Pricing, and Market Segmentation", in MS 2026 per OpenAlex).

Fields in `data/rr_candidates.json`: title, title_confidence, journal, journal_match_text, journal_distance_chars, status_phrase, author_name, openalex_id, source_url, page_kind, snippet (300 characters or fewer, whitespace-collapsed page text), flags, already_published_match, checked_date, candidate_id. `data/scan_fetch_log.csv` logs every fetch.

## Runtime of a full weekly run (estimate, not measured)

| Step | Scope | Runtime |
|---|---|---|
| 1 | full cohort | about 2-3 min, measured 134 s |
| 2a | all ORCIDs | about 12 min, measured 725 s. A weekly run could re-query only new ORCIDs and refresh the rest monthly. |
| 2b | all 657 institutions | not run. Extrapolated from 104 s for 40 institutions (bounded by per-host 1 req/s), it would take roughly 10-30 min, for little yield. |
| 3 | about 1,500 authors with URLs (full cohort) | not run. Extrapolated from 74 s for 150 authors with 10 threads, it would take roughly 12-20 min. The extrapolation is uncertain because shared hosts (sites.google.com) serialise at 1 req/s. |

The total is roughly 30-60 minutes a week on one machine.

## Known failure modes

1. **Stale R&Rs.** Pages are often not updated after acceptance. In the sample, Cong's page still says "2022, Management Science, R&R" for a paper OpenAlex lists as published in MS in 2026. Briscoe-Tran's page has an "R&R at Management Science" news line next to "Accepted at Management Science". The title-match check catches only exact-ish titles in the six journals, and only once OpenAlex has indexed the article.
2. **Referee-role mentions.** Lines such as "Referee: The Accounting Review" carry no status phrase, so they do not match. Explicit "ad hoc reviewer ... second round" text would be flagged by `flag_referee_context`, but this did not occur in the sample.
3. **Ambiguous abbreviations.** CAR (cumulative abnormal returns), MS (master's degree) and RAS are case-sensitive word matches and must be attached to the phrase. Residual risk remains: for example, "MS, R&R" in an unrelated context.
4. **Name disambiguation.** OpenAlex sometimes splits one person into several author ids: 41 ORCIDs are shared by more than one author id, for example "AJ Chen" and "AJ Yuan Chen". It can also attach the wrong ORCID; 55 URL rows fail the family-name check. A site should group by ORCID or by normalised name, as the finance tracker's "author name groups" do.
5. **Coverage.** Only 14.5% of accounting-5 authors expose a URL in ORCID. Pure research portals (`research.*`, `scholars.*`, `pure.*`, `experts.*`) return 403 to non-browser clients. JavaScript-rendered sites (Wix and similar) yield little text, and this was not measured.
6. **Title extraction.** It depends on page layout. In the sample it failed for Zha Giedt, where the extracted "title" is a fragment of an abstract, and gave only a description for Briscoe-Tran ("My job market paper on ESG"). Low-confidence titles need human review before publication.
7. **R&R at other journals.** These are dropped by design (JFE, EAR, Financial Management in the sample).
8. **Recall within a page.** Formats such as "R&R (JAR)" or "Status: second round at TAR" are partly covered. Phrases outside the regex, such as "invited to revise" or "major revision", are not matched.

## Verification status

See the "Independent verification" section below, which a separate monitor agent fills in after re-deriving the claims with its own code.

## Independent verification (monitor agent, own code, 2026-10-15)

- **A. Source ids: CONFIRMED.** The monitor re-ran the ISSN lookups and got the same six ids.
- **B. Article counts: WORKER-REPORTED only.** The OpenAlex free daily budget for this IP ran out during monitoring, so the counts were not re-derived.
  - The counts 287/266/590/461/375/2,417 are OpenAlex `meta.count` values, and they equal the number of works the script paged through (log line `works: N (meta count N)`).
  - `cohort_works.csv` holds only works that have at least one authorship with an author id. Distinct works there: JAE 284, JAR 257, TAR 552, CAR 451, RAST 372, MS 2,390, total 4,306. The 90 missing works have no author id in OpenAlex, so they contribute no one to the cohort.
  - To resolve: re-run one `group_by` query after the budget resets, or with an API key.
- **C. Cohort: CONFIRMED.** The monitor recomputed 7,470 author ids and 2,806 accounting-5 authors from `cohort_works.csv`. The per-journal counts match exactly. 5 random works matched the OpenAlex API.
  - Caveat: these are OpenAlex ids, not people. Collapsing ids that share an ORCID gives about 2,788 distinct accounting-5 people.
- **D. ORCID coverage: CONFIRMED.** The monitor re-queried 40 random accounting-5 ORCIDs: "has a URL" agreed 40/40, and the exact URL sets matched for all 20 listed authors.
- **E. Candidates.** All 12 snippets appear verbatim on the live pages, and none is a referee role or a different journal.
  - **10 of 12 are genuine, current R&Rs at the named journal.**
  - **2 are stale:** #1 (Briscoe-Tran) and #9 (Cong). Both papers were published in Management Science in 2026. The staleness check caught #9 but missed #1, because #1's "title" is a description ("My job market paper on ESG").
  - **Title errors:** #10's title is an abstract fragment (the real title on SSRN is "Companies' Strategic Reviews: Determinants and Outcomes"). #1 is not a title.
  - **`title_confidence` is miscalibrated:** #1 is marked high but is wrong, and #11 and #12 are marked low but are right.
  - **Required before publishing:** a second staleness route (Crossref title search, or author plus journal), and human review of every low-confidence or descriptive title.

## Step 2c: curated faculty directories (`02c_directories.py`), added 2026-10-16

- **List:** `data/directories/faculty_directories.csv` covers the 150 schools with the most accounting-5 authors (1,837 of 2,806 author ids). The three non-schools in the raw ranking were replaced by the next schools: NBER, ECGI and ZEW. Three agents built the list, one batch of 50 each, and fetched every URL they recorded.
  - Render: static 115, js 18, blocked 13, none 4.
  - After the corrections below, 147 schools have a directory URL or a profile example.
- **Independent check:** a separate agent checked 40 random rows with its own fetches. 36 OK, 3 partial (blank profile example), 1 wrong. The render label agreed in 40/40.
  - UNSW: the page lists only leadership, so it is now render=none and reached only through the slug route.
  - Oklahoma State: the agent found a directory the batch had missed, experts.okstate.edu/groups/60/experts, which is now added.
  - Both corrections apply from the next run onward.
- **Route:**
  - For a static directory, the route looks for anchors carrying the author's first and last name. Otherwise it substitutes the name into the example profile URL's slug.
  - The profile page must carry both name tokens in its `<title>` or `<h1>`.
  - Out-links count as a personal site only if the author's name is in the URL; CV PDFs are matched by file name.
  - The first run also accepted anchor text such as "Website", which picked up footer links (privacy notices, alumni pages). That rule was tightened, and the existing output was re-filtered: 1,612 to 1,350 rows.
- **Result (logs/02c_directories.log):** 857 authors matched to a profile page, with 236 personal-site links and 257 CV links.
- **Spot check:** 10/10 random profile matches were the right person.

## Full scan 2026-10-16 (logs/03_scan_full.log)

- 1,120 accounting-5 authors had at least one crawlable URL from ORCID or the directories. The scan made 3,421 fetches, 3,071 of them HTTP 200.
- **Coverage, in people** (author ids sharing an ORCID count as one person): 1,074 of 2,788 accounting-5 people had at least one page read successfully, **38.5%**. The ORCID-only prototype reached about 15%.
- **Candidates:** 145, from 73 authors. 4 are flagged as already published, 3 by OpenAlex titles and 4 by Crossref, overlapping. The other 141 went to independent review.

## Step 4: Crossref staleness (`04_staleness.py`)

A candidate counts as already published when Crossref has a journal article, in any journal, with title similarity of at least 0.90 that includes the candidate's family name among its authors.
- Positive control: on the 12 prototype candidates it independently caught Cong et al. (MS 2026).
- It cannot catch descriptive "titles" such as Briscoe-Tran's, so the human-level review remains required.

## Step 5: review and publish (`05_publish.py`)

- Only candidates with verdict `publish` in `data/rr_review.json` reach `data/rr_public.json`, which is the only tracker data file that is committed.
- The review is done by independent agents with their own fetches. Each confirms that the page is the author's, that it shows a current R&R at the named journal, the exact title on the page, and no published version on Crossref or the web.
- `build.py` generates the AcctRes page (`rr-tracker/index.html`) from `rr_public.json`.
