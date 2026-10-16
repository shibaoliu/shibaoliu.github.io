#!/usr/bin/env python3
"""Build shibaoliu.github.io from data/site.json and data/papers.json.

Usage:  python3 build.py
Writes index.html, research.html, teaching.html, presentations.html, cv.html,
papers/<slug>.html, feed.xml and sitemap.xml next to this file.
Standard library only. Never hand-edit the generated HTML.
"""
import json
import re
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = json.loads((ROOT / "data/site.json").read_text())
PAPERS_DATA = json.loads((ROOT / "data/papers.json").read_text())
PAPERS = PAPERS_DATA["papers"]
THEMES = PAPERS_DATA["themes"]
# The AcctRes tab is built only from reviewed tracker entries (rr-tracker/data/rr_public.json).
TRACKER_FILE = ROOT / "rr-tracker/data/rr_public.json"
TRACKER = json.loads(TRACKER_FILE.read_text()) if TRACKER_FILE.exists() else None
BY_SLUG = {p["slug"]: p for p in PAPERS}
BASE = SITE["domain"].rstrip("/")

STATUS_LABEL = {
    "review": "Under Review",
    "working": "Working Paper",
    "progress": "Work in Progress",
    "published": "Published",
}


def nav_items():
    items = [("index.html", "Home"), ("cv.html", "CV"), ("research.html", "Research"),
             ("teaching.html", "Teaching"), ("presentations.html", "Presentations")]
    # The AcctRes (R&R tracker) tab appears only once reviewed tracker data exist.
    if TRACKER:
        items.append(("rr-tracker/index.html", "AcctRes"))
    return items


def e(s):
    return escape(s or "", quote=True)


def join_names(names):
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def authors_line(p):
    return ("with " + join_names(p["coauthors"])) if p["coauthors"] else ""


def links_for(p, prefix=""):
    out = []
    if p.get("journal"):
        out.append(("Journal", p["journal"], True))
    if p.get("ssrn"):
        out.append(("SSRN", p["ssrn"], True))
    if p.get("pdf"):
        out.append(("PDF", prefix + p["pdf"], True))
    return out


def a(label, href, new_tab=False):
    tgt = ' target="_blank" rel="noopener"' if new_tab else ""
    return f'<a href="{e(href)}"{tgt}>{label}</a>'


def bibtex(p):
    last = SITE["name"].split()[-1].lower()
    words = [re.sub(r"[^a-z]", "", w.lower()) for w in p["title"].split()]
    words = [w for w in words if w and w not in {"a", "an", "the", "do", "of"}]
    key = f'{last}{p["year"]}{words[0] if words else "paper"}'
    authors = " and ".join([SITE["name"]] + p["coauthors"])
    if p["status"] == "published":
        lines = ["@article{" + key, f"  author = {{{authors}}}", f"  title = {{{p['title']}}}",
                 f"  journal = {{{p.get('venue', '')}}}", f"  year = {{{p['year']}}}"]
    else:
        note = "Working paper"
        if p.get("note"):
            note += "; " + p["note"][0].lower() + p["note"][1:]
        lines = ["@unpublished{" + key, f"  author = {{{authors}}}", f"  title = {{{p['title']}}}",
                 f"  year = {{{p['year']}}}", f"  note = {{{note}}}"]
    if p.get("ssrn"):
        lines.append(f"  url = {{{p['ssrn']}}}")
    return ",\n".join(lines) + "\n}"


def has_page(p):
    """A paper gets its own page only when there is something beyond the card."""
    return bool(p.get("abstract") or p.get("presentations"))


def paper_href(p, prefix=""):
    return f'{prefix}papers/{p["slug"]}.html' if has_page(p) else f'{prefix}research.html#{p["slug"]}'


def active_links(prefix=""):
    out = []
    for l in SITE["links"]:
        if not l["url"]:
            continue
        url = l["url"]
        # A local file that is not there yet (e.g. the CV PDF) falls back to cv.html.
        if not url.startswith(("http", "mailto:")):
            url = prefix + (url if (ROOT / url).exists() else "cv.html")
        out.append(dict(l, url=url))
    return out


def page(title, body, active="", prefix="", description="", canonical="", prerender=()):
    cur = ' class="active" aria-current="page"'
    nav = "\n".join(f'      <a href="{prefix}{href}"{cur if href == active else ""}>{label}</a>'
                    for href, label in nav_items())
    desc = e(description or f'{SITE["name"]}, {SITE["title"]}, {SITE["affiliation"]}.')
    canon = BASE + "/" + canonical
    spec = ""
    if prerender:
        spec = ('<script type="speculationrules">'
                + json.dumps({"prerender": [{"urls": list(prerender), "eagerness": "moderate"}]})
                + "</script>")
    ga = ""
    if SITE.get("analytics_id"):
        gid = e(SITE["analytics_id"])
        ga = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={gid}"></script>\n'
              f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
              f"gtag('js',new Date());gtag('config','{gid}');</script>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{e(canon)}">
<meta property="og:type" content="profile">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{e(canon)}">
<meta property="og:image" content="{BASE}/assets/og-card.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="color-scheme" content="light dark">
<link rel="preload" href="{prefix}assets/fonts/source-serif-4.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{prefix}assets/fonts/inter.woff2" as="font" type="font/woff2" crossorigin>
<link rel="icon" type="image/svg+xml" href="{prefix}assets/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="{prefix}assets/favicon-32.png">
<link rel="apple-touch-icon" href="{prefix}assets/apple-touch-icon.png">
<link rel="alternate" type="application/atom+xml" title="{e(SITE['name'])}: Research" href="{prefix}feed.xml">
<link rel="stylesheet" href="{prefix}assets/site.css">
{spec}
{ga}
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header">
  <div class="wrap">
    <div class="wordmark"><a href="{prefix}index.html">{e(SITE['name'])}</a></div>
    <nav class="site-nav" aria-label="Primary">
{nav}
    </nav>
  </div>
</header>
{body}
<footer class="site-footer">
  <div class="wrap">
    <span>&copy; {date.today().year} {e(SITE['name'])}</span>
    <span>{e(SITE['affiliation'])} &middot; <a href="mailto:{e(SITE['email'])}">{e(SITE['email'])}</a></span>
  </div>
</footer>
<script src="{prefix}assets/site.js" defer></script>
</body>
</html>
"""


def page_hero(kind, eyebrow, h1, lede, stats=""):
    stats_html = f'<p class="hero-stats">{stats}</p>' if stats else ""
    return f"""<section class="page-hero ph-{kind}">
  <div class="wrap">
    <div class="eyebrow">{eyebrow}</div>
    <h1>{h1}</h1>
    <p class="lede">{lede}</p>
    {stats_html}
  </div>
</section>"""


# ── AcctRes: accounting R&R tracker ─────────────────────────────────
JOURNAL_NAME = {"JAE": "Journal of Accounting and Economics", "JAR": "Journal of Accounting Research",
                "TAR": "The Accounting Review", "CAR": "Contemporary Accounting Research",
                "RAST": "Review of Accounting Studies", "MS": "Management Science"}


def build_tracker():
    T, pre = TRACKER, "../"
    entries = sorted(T["entries"], key=lambda x: (list(JOURNAL_NAME).index(x["journal"]), x["title"].lower()))
    cards = []
    for i, x in enumerate(entries):
        who = "; ".join(f'{e(au["name"])} (<a href="{e(au["source_url"])}" target="_blank" rel="noopener">source</a>, '
                        f'checked {e(au["checked_date"])})' for au in x["authors"])
        names = " ".join(au["name"] for au in x["authors"])
        quote = "".join(f'<blockquote>{e(au["snippet"])}</blockquote>' for au in x["authors"])
        search = " ".join([x["title"], names, x["journal"], JOURNAL_NAME[x["journal"]]]).lower()
        cards.append(f"""<article class="paper rr" data-journal="{x['journal']}" data-order="{i}"
  data-title="{e(x['title'].lower())}" data-author="{e(x['authors'][0]['name'].split()[-1].lower())}"
  data-checked="{e(max(au['checked_date'] for au in x['authors']))}" data-search="{e(search)}">
  <div class="paper-head"><span class="paper-kicker">{e(JOURNAL_NAME[x['journal']])}</span><span class="status-pill status-review">R&amp;R &middot; {x['journal']}</span></div>
  <h3>{e(x['title'])}</h3>
  <p class="paper-authors">Listed by {who}</p>
  <details class="paper-abstract"><summary>Wording on the author's page</summary>{quote}</details>
</article>""")
    counts = {j: sum(x["journal"] == j for x in entries) for j in JOURNAL_NAME}
    chips = [f'<button type="button" class="chip" data-journal="all" aria-pressed="true">All<span class="chip-n">{len(entries)}</span></button>']
    chips += [f'<button type="button" class="chip" data-journal="{j}" aria-pressed="false">{j}<span class="chip-n">{n}</span></button>'
              for j, n in counts.items() if n]
    c = T["coverage"]
    stats = (f'{len(entries)} R&amp;R papers &middot; {c["authors_reached"]:,} of {c["authors_total"]:,} authors reached '
             f'({100 * c["authors_reached"] / c["authors_total"]:.1f}%) &middot; last run {e(T["generated"])}')
    hero = page_hero("research", "AcctRes", "Accounting R&amp;R Tracker",
                     "Working papers that their authors publicly list as revise-and-resubmit at the five leading "
                     "accounting journals (JAE, JAR, TAR, CAR, RAST) and Management Science.", stats)
    method = "".join(f"<li>{m}</li>" for m in T["method"])
    body = f"""{hero}
<div class="research-toolbar">
  <div class="wrap rt-row">
    <label class="visually-hidden" for="rt-search">Search the tracker</label>
    <input id="rt-search" class="rt-search" type="search" placeholder="Search titles and authors&hellip;">
    <div class="chips" role="group" aria-label="Filter by journal">{''.join(chips)}</div>
    <div class="rt-sort">
      <label for="rt-sort" class="rt-sort-label">Sort</label>
      <select id="rt-sort" class="rt-select">
        <option value="journal">By journal</option>
        <option value="author">Author A&ndash;Z</option>
        <option value="title">Title A&ndash;Z</option>
        <option value="checked">Recently checked</option>
      </select>
    </div>
    <span id="rt-count" class="rt-count" aria-live="polite"></span>
  </div>
</div>
<main id="main" tabindex="-1" class="main research-main">
  <div class="wrap">
    <div id="rr-list">
{chr(10).join(cards)}
    </div>
    <p id="rt-empty" class="empty-state" hidden>No papers match that search.</p>
    <section class="rr-method">
      <h2 class="section-label">How this list is built</h2>
      <ul class="rail-list">{method}</ul>
    </section>
  </div>
</main>"""
    return page(f'AcctRes: Accounting R&R Tracker | {SITE["name"]}', body, "rr-tracker/index.html", prefix=pre,
                canonical="rr-tracker/index.html",
                description="Working papers publicly listed as revise-and-resubmit at JAE, JAR, TAR, CAR, RAST and Management Science.")


# ── Home ─────────────────────────────────────────────────────────────
def build_home():
    if SITE.get("photo"):
        photo = f'<img src="{e(SITE["photo"])}" alt="{e(SITE["name"])}" width="520" height="650" fetchpriority="high">'
    else:
        initials = "".join(w[0] for w in SITE["name"].split())
        photo = f'<div class="monogram" aria-hidden="true">{initials}</div>'

    news = []
    for n in SITE["news"]:
        p = BY_SLUG.get(n.get("paper", ""))
        if p:
            title = a(e(p["title"]), paper_href(p))
            bits = []
            if p["coauthors"]:
                bits.append(e(authors_line(p)))
            bits.append(f'<em>{e(n["meta"])}</em>')
            if n.get("summary"):
                bits.append(e(n["summary"]))
            lk = []
            if has_page(p):
                lk.append(a("Paper page", paper_href(p)))
            lk += [a(lbl, href, nt) for lbl, href, nt in links_for(p)]
            if lk:
                bits.append(" &middot; ".join(lk))
            meta = " &middot; ".join(bits)
        else:
            title = e(n["title"])
            meta = e(n["meta"])
        news.append(f"""    <div class="announce-item">
      <span class="announce-tag">{e(n['tag'])}</span>
      <div><div class="announce-title">{title}</div><div class="announce-meta">{meta}</div></div>
    </div>""")

    about = "\n        ".join(f"<p>{para}</p>" for para in SITE["about"])
    edu = "\n".join(f'          <li><div class="primary">{e(x["degree"])}</div><div class="secondary">{e(x["school"])}</div></li>'
                    for x in SITE["education"])

    def rail(items):
        return "".join(f"<li>{x}</li>" for x in items)

    n_current = sum(p["status"] != "published" for p in PAPERS)
    n_talks = len(SITE.get("presentations", []))
    tracker = ""
    if TRACKER:
        tracker = ('<div class="rail-block"><div class="rail-heading">AcctRes: R&amp;R Tracker</div>'
                   f'<div class="rail-note">{len(TRACKER["entries"])} working papers that authors publicly list as revise-and-resubmit at JAE, JAR, '
                   'TAR, CAR, RAST and Management Science.<br>'
                   '<a href="rr-tracker/index.html">Open the tracker &rarr;</a></div></div>')

    sameas = [l["url"] for l in active_links() if l["url"].startswith("http")]
    ld = {"@context": "https://schema.org", "@type": "Person", "name": SITE["name"],
          "url": BASE + "/", "jobTitle": SITE["title"], "email": "mailto:" + SITE["email"],
          "image": BASE + "/assets/og-card.png",
          "affiliation": [{"@type": "Organization", "name": x} for x in SITE.get("affiliations", [SITE["affiliation"]])],
          "alumniOf": [{"@type": "CollegeOrUniversity", "name": "University of Illinois Chicago"},
                       {"@type": "CollegeOrUniversity", "name": "Xiamen University"}]}
    if sameas:
        ld["sameAs"] = sameas

    roles = "<br>\n        ".join(e(r) for r in SITE.get("role_lines", [f'{SITE["title"]}, {SITE["affiliation"]}']))
    links = "\n        ".join(a(e(l["label"]), l["url"], l["url"].startswith("http")) for l in active_links())

    body = f"""<script type="application/ld+json">{json.dumps(ld)}</script>
<section class="hero">
  <div class="wrap">
    <div>
      <h1>{e(SITE['name'])}</h1>
      <p class="hero-role">
        {roles}
      </p>
      <p class="hero-lede">{e(SITE['lede'])}</p>
      <div class="hero-links">
        {links}
      </div>
    </div>
    <div class="hero-photo">{photo}</div>
  </div>
</section>

<div class="announce">
  <div class="wrap announce-stack">
    <div class="announce-heading">Latest Research Updates &middot; <a href="feed.xml">RSS</a></div>
{chr(10).join(news)}
  </div>
</div>

<main id="main" tabindex="-1" class="main">
  <div class="wrap cols">
    <div>
      <div class="block prose">
        <h2 class="section-label">About</h2>
        {about}
      </div>
      <div class="block">
        <h2 class="section-label">Education</h2>
        <ul class="row-list">
{edu}
        </ul>
      </div>
    </div>
    <aside>
      <div class="rail-block"><div class="rail-heading">Research Interests</div><ul class="rail-list">{rail(e(x) for x in SITE['interests'])}</ul></div>
      <div class="rail-block"><div class="rail-heading">Reviewing</div><ul class="rail-list">{rail(SITE.get('reviewing', []))}</ul></div>
      <div class="rail-block"><div class="rail-heading">Affiliations</div><ul class="rail-list">{rail(e(x) for x in SITE.get('affiliations', []))}</ul></div>
      <div class="rail-block"><div class="rail-heading">Research</div><div class="rail-note">{n_current} current papers on voluntary and mandatory disclosure, financial analysts, and research methods.<br><a href="research.html">See all papers &rarr;</a></div></div>
      {tracker}
      <div class="rail-block"><div class="rail-heading">Presentations</div><div class="rail-note">{n_talks} conference presentations, consortia, and workshops since 2013, including AAA, FARS, CAR, Kellogg, and Wharton.<br><a href="presentations.html">See the list &rarr;</a></div></div>
      <div class="rail-block"><div class="rail-heading">Selected Honors</div><ul class="rail-list">{rail(e(x) for x in SITE['awards'])}</ul></div>
      <div class="rail-block"><div class="rail-heading">Service</div><ul class="rail-list">{rail(SITE['service'])}</ul></div>
      <div class="rail-block"><div class="rail-heading">Contact</div><div class="rail-note"><a href="mailto:{e(SITE['email'])}">{e(SITE['email'])}</a><br>{'<br>'.join(e(x) for x in SITE['address'])}</div></div>
    </aside>
  </div>
</main>"""
    return page(f'{SITE["name"]}, {SITE["affiliation"]}', body, "index.html",
                description=f'{SITE["name"]} is an {SITE["title"]} at the {SITE["affiliation"]}. {SITE["lede"]}',
                prerender=("research.html", "teaching.html"))


# ── Research ─────────────────────────────────────────────────────────
def paper_card(p, i):
    title_html = a(e(p["title"]), paper_href(p)) if has_page(p) else e(p["title"])
    kicker = f'<span class="paper-kicker">{e(p.get("venue", ""))} &middot; {p["year"]}</span>' if p["status"] == "published" else ""
    note = f'<p class="paper-note">{e(p["note"])}</p>' if p.get("note") else ""
    if p["status"] == "published" and p.get("cite"):
        note = f'<p class="paper-authors"><em>{e(p["venue"])}</em>, {p["year"]}, {e(p["cite"])}</p>'
    authors = f'<p class="paper-authors">{e(authors_line(p))}</p>' if p["coauthors"] else ""
    abstract = (f'<details class="paper-abstract"><summary>Abstract</summary><p>{e(p["abstract"])}</p></details>'
                if p.get("abstract") else "")
    links = [a("Paper Page", paper_href(p))] if has_page(p) else []
    links += [a(lbl, href, nt) for lbl, href, nt in links_for(p)]
    links.append(f'<button type="button" class="bib-btn" data-bib="{p["slug"]}">BibTeX</button>')
    search = " ".join([p["title"], " ".join(p["coauthors"]), p.get("note", ""), p.get("venue", ""),
                       STATUS_LABEL[p["status"]], THEMES.get(p["theme"], ""), p.get("abstract", "")]).lower()
    return f"""<article class="paper" id="{p['slug']}" style="view-transition-name:p-{p['slug']}"
  data-status="{p['status']}" data-year="{p['year']}" data-order="{i}" data-title="{e(p['title'].lower())}" data-search="{e(search)}">
  <div class="paper-head">{kicker}<span class="status-pill status-{p['status']}">{STATUS_LABEL[p['status']]}</span></div>
  <h3>{title_html}</h3>
  {authors}
  {note}
  {abstract}
  <div class="entry-links">{' '.join(links)}</div>
  <script type="text/x-bibtex" id="bib-{p['slug']}">{e(bibtex(p))}</script>
</article>"""


def build_research():
    groups, i = [], 0
    for key, label in THEMES.items():
        cards = []
        for p in PAPERS:
            if p["theme"] == key:
                cards.append(paper_card(p, i))
                i += 1
        if cards:
            groups.append(f'<section class="theme-group" data-theme="{key}"><h2>{e(label)}</h2>\n' + "\n".join(cards) + "</section>")
    counts = {s: sum(p["status"] == s for p in PAPERS) for s in STATUS_LABEL}
    chips = [f'<button type="button" class="chip" data-status="all" aria-pressed="true">All<span class="chip-n">{len(PAPERS)}</span></button>']
    chips += [f'<button type="button" class="chip" data-status="{s}" aria-pressed="false">{STATUS_LABEL[s]}<span class="chip-n">{n}</span></button>'
              for s, n in counts.items() if n]
    stats = " &middot; ".join([f"{len(PAPERS)} papers"] + [f"{n} {STATUS_LABEL[s].lower()}" for s, n in counts.items() if n])
    hero = page_hero("research", "Research", "Working Papers &amp; Publications",
                     "Corporate voluntary and mandatory disclosure, financial analysts, disclosure regulation, "
                     "and their implications for capital markets.", stats)
    body = f"""{hero}
<div class="research-toolbar">
  <div class="wrap rt-row">
    <label class="visually-hidden" for="rt-search">Search papers</label>
    <input id="rt-search" class="rt-search" type="search" placeholder="Search titles, coauthors, abstracts&hellip;">
    <div class="chips" role="group" aria-label="Filter by status">{''.join(chips)}</div>
    <div class="rt-sort">
      <label for="rt-sort" class="rt-sort-label">Sort</label>
      <select id="rt-sort" class="rt-select">
        <option value="topic">By topic</option>
        <option value="status">By status</option>
        <option value="year">Newest first</option>
        <option value="title">Title A&ndash;Z</option>
      </select>
    </div>
    <span id="rt-count" class="rt-count" aria-live="polite"></span>
  </div>
</div>
<main id="main" tabindex="-1" class="main research-main">
  <div class="wrap">
    <div id="paper-list">
{chr(10).join(groups)}
    </div>
    <div id="flat-list" hidden></div>
    <p id="rt-empty" class="empty-state" hidden>No papers match that search.</p>
    <p class="footnote">* Presented by a coauthor.</p>
  </div>
</main>"""
    return page(f'Research | {SITE["name"]}', body, "research.html", canonical="research.html",
                description=f'Working papers and publications by {SITE["name"]}.')


def build_paper_page(p):
    note = f'<p class="paper-note">{e(p["note"])}</p>' if p.get("note") else ""
    abstract = f'<h2>Abstract</h2><p class="abstract-text">{e(p["abstract"])}</p>' if p.get("abstract") else ""
    pres = ""
    if p.get("presentations"):
        pres = ("<h2>Presentations</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in p["presentations"]) + "</ul>"
                + ('<p class="footnote">* Presented by a coauthor.</p>' if any("*" in x for x in p["presentations"]) else ""))
    links = [a(lbl, href, nt) for lbl, href, nt in links_for(p, "../")]
    links.append(f'<button type="button" class="bib-btn" data-bib="{p["slug"]}">Copy BibTeX</button>')
    kicker = f'<span class="paper-kicker">{e(THEMES.get(p["theme"], ""))}</span>'
    body = f"""<main id="main" tabindex="-1" class="paper-page">
  <div class="wrap" style="view-transition-name:p-{p['slug']}">
    <a class="crumb" href="../research.html">&larr; All research</a>
    <div class="paper-head">{kicker}<span class="status-pill status-{p['status']}">{STATUS_LABEL[p['status']]}</span></div>
    <h1>{e(p['title'])}</h1>
    <p class="paper-authors">{e(join_names([SITE['name']] + p['coauthors']))}</p>
    {note}
    <div class="entry-links">{' '.join(links)}</div>
    {abstract}
    {pres}
    <h2>Citation</h2>
    <pre class="bib" id="bib-{p['slug']}">{e(bibtex(p))}</pre>
  </div>
</main>"""
    return page(f'{p["title"]} | {SITE["name"]}', body, "", "../", canonical=f'papers/{p["slug"]}.html',
                description=(p.get("abstract") or p["title"])[:300])


# ── Teaching ─────────────────────────────────────────────────────────
def build_teaching():
    groups = []
    for g in SITE["teaching"]:
        rows = "".join(
            f'<div class="course"><span class="name">{e(c["name"])}</span><span class="when">{e(c["when"])}</span>'
            f'<span class="detail">{e(c["level"])}{(" &middot; " + e(c["rating"])) if c.get("rating") else ""}</span></div>'
            for c in g["courses"])
        groups.append(f'<div class="course-group"><h3>{e(g["institution"])}</h3><p class="role">{e(g["role"])}</p>{rows}</div>')
    notes = "".join(f"<li>{x}</li>" for x in SITE["teaching_notes"])
    hero = page_hero("teaching", "Teaching", "Financial &amp; Managerial Accounting",
                     "Undergraduate core courses at Florida Tech and the University of Illinois Chicago. "
                     "Ratings are student evaluations on a five-point scale.")
    body = f"""{hero}
<main id="main" tabindex="-1" class="main">
  <div class="wrap cols">
    <div>{''.join(groups)}</div>
    <aside><div class="rail-block"><div class="rail-heading">Teaching Development</div><ul class="rail-list">{notes}</ul></div></aside>
  </div>
</main>"""
    return page(f'Teaching | {SITE["name"]}', body, "teaching.html", canonical="teaching.html")


# ── Presentations ────────────────────────────────────────────────────
def build_presentations():
    rows = SITE.get("presentations", [])
    by_year = {}
    for name, when, role in rows:
        by_year.setdefault(when.split()[-1], []).append((name, when, role))
    blocks = []
    for yr in sorted(by_year, reverse=True):
        lis = "".join(f'<li><span>{e(n)}{(" <em>(" + e(r) + ")</em>") if r else ""}</span><span class="d">{e(w)}</span></li>'
                      for n, w, r in by_year[yr])
        blocks.append(f'<div class="tl-year"><h2 class="section-label">{yr}</h2><ul class="dated-list">{lis}</ul></div>')
    n_role = sum(1 for r in rows if r[2])
    hero = page_hero("presentations", "Presentations", "Conferences &amp; Workshops",
                     "Conference presentations, discussions, doctoral consortia, and workshops.",
                     f"{len(rows)} events &middot; {n_role} as presenter, discussant, or moderator &middot; {min(by_year)}&ndash;{max(by_year)}")
    body = f"""{hero}
<main id="main" tabindex="-1" class="main">
  <div class="wrap" style="max-width:860px">
    {''.join(blocks)}
  </div>
</main>"""
    return page(f'Presentations | {SITE["name"]}', body, "presentations.html", canonical="presentations.html")


# ── CV ───────────────────────────────────────────────────────────────
def build_cv():
    cv_link = next((l["url"] for l in SITE["links"] if l["label"] == "Curriculum Vitae" and l["url"]), "")
    cta = (f'<a class="cv-cta" href="{e(cv_link)}" target="_blank" rel="noopener">Download CV (PDF)</a>'
           if cv_link and (ROOT / cv_link).exists() else "")
    edu = "".join(f'<li><span>{e(x["degree"])}, {e(x["school"])}</span></li>' for x in SITE["education"])
    cur = [p for p in PAPERS if p["status"] != "published"]
    pre = [p for p in PAPERS if p["status"] == "published"]
    cur_li = "".join(f'<li><span>{a("&ldquo;" + e(p["title"]) + "&rdquo;", paper_href(p))}{(", " + e(authors_line(p))) if p["coauthors"] else ""}'
                     f'{(" &middot; <em>" + e(p["note"]) + "</em>") if p.get("note") else ""}</span></li>' for p in cur)
    pre_li = "".join(f'<li><span>&ldquo;{e(p["title"])}&rdquo;, {e(authors_line(p))}, <em>{e(p["venue"])}</em></span>'
                     f'<span class="d">{p["year"]}</span></li>' for p in pre)
    hero = page_hero("cv", "Curriculum Vitae", e(SITE["name"]),
                     "A summary of my CV. The PDF has the full record of presentations, service, and honors.")
    body = f"""{hero}
<main id="main" tabindex="-1" class="main">
  <div class="wrap" style="max-width:860px">
    {cta}
    <div class="block"><h2 class="section-label">Academic Employment</h2><ul class="dated-list">
      <li><span>{e(SITE['title'])}, {e(SITE['affiliation'])}</span><span class="d">2025&ndash;present</span></li></ul></div>
    <div class="block"><h2 class="section-label">Education</h2><ul class="dated-list">{edu}</ul></div>
    <div class="block"><h2 class="section-label">Working Papers</h2><ul class="dated-list">{cur_li}</ul></div>
    <div class="block"><h2 class="section-label">Pre-Doctoral Publications</h2><ul class="dated-list">{pre_li}</ul></div>
    <div class="block"><h2 class="section-label">Honors</h2><ul class="dated-list">{''.join(f'<li><span>{e(x)}</span></li>' for x in SITE['awards'])}</ul></div>
    <div class="block"><h2 class="section-label">Reviewing &amp; Service</h2><ul class="dated-list">{''.join(f'<li><span>{x}</span></li>' for x in SITE.get('reviewing', []) + SITE['service'])}</ul></div>
  </div>
</main>"""
    return page(f'CV | {SITE["name"]}', body, "cv.html", canonical="cv.html")


# ── Feed + sitemap ───────────────────────────────────────────────────
def build_feed():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = []
    for p in [p for p in PAPERS if p["status"] != "published"]:
        url = BASE + "/" + paper_href(p)
        summary = ". ".join(x for x in [authors_line(p), p.get("note", ""), STATUS_LABEL[p["status"]]] if x)
        entries.append(f"""  <entry><title>{e(p['title'])}</title><link href="{url}"/><id>{url}</id><updated>{now}</updated>
    <summary>{e(summary)}</summary></entry>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{e(SITE['name'])}: Research</title>
  <link href="{BASE}/"/><link rel="self" href="{BASE}/feed.xml"/>
  <id>{BASE}/</id><updated>{now}</updated><author><name>{e(SITE['name'])}</name></author>
{chr(10).join(entries)}
</feed>
"""


def build_sitemap(paths):
    urls = "\n".join(f"  <url><loc>{BASE}/{'' if p == 'index.html' else p}</loc></url>" for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n'


def main():
    out = {"index.html": build_home(), "research.html": build_research(),
           "teaching.html": build_teaching(), "presentations.html": build_presentations(),
           "cv.html": build_cv()}
    papers_dir = ROOT / "papers"
    papers_dir.mkdir(exist_ok=True)
    for old in papers_dir.glob("*.html"):
        old.unlink()
    for p in PAPERS:
        if has_page(p):
            out[f'papers/{p["slug"]}.html'] = build_paper_page(p)
    out["feed.xml"] = build_feed()
    pages = [k for k in out if k.endswith(".html")]
    if TRACKER:
        out["rr-tracker/index.html"] = build_tracker()
        pages.append("rr-tracker/index.html")
    out["sitemap.xml"] = build_sitemap(pages)
    for path, text in out.items():
        (ROOT / path).write_text(text)
    print(f"Built {len(out)} files.")


if __name__ == "__main__":
    main()
