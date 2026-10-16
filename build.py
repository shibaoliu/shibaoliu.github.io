#!/usr/bin/env python3
"""Build shibaoliu.com from data/site.json and data/papers.json.

Usage:  python3 build.py
Writes index.html, research.html, teaching.html, cv.html, papers/<slug>.html,
feed.xml and sitemap.xml next to this file. Standard library only.
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
BY_SLUG = {p["slug"]: p for p in PAPERS}

STATUS_LABEL = {
    "review": "Under Review",
    "working": "Working Paper",
    "progress": "Work in Progress",
    "published": "Published",
}
NAV = [("index.html", "Home"), ("research.html", "Research"),
       ("teaching.html", "Teaching"), ("cv.html", "CV")]
FONTS = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600"
         "&family=JetBrains+Mono:wght@400;500"
         "&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap")


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


def kicker(p):
    if p["status"] == "published":
        return f'{p.get("venue", "")} · {p["year"]}'
    return ""


def links_for(p, prefix=""):
    out = []
    if p.get("journal"):
        out.append(f'<a href="{e(p["journal"])}" target="_blank" rel="noopener">Journal</a>')
    if p.get("ssrn"):
        out.append(f'<a href="{e(p["ssrn"])}" target="_blank" rel="noopener">SSRN</a>')
    if p.get("pdf"):
        out.append(f'<a href="{prefix}{e(p["pdf"])}" target="_blank" rel="noopener">PDF</a>')
    return out


def bibtex(p):
    last = SITE["name"].split()[-1].lower()
    first_word = re.sub(r"[^a-z]", "", p["title"].split()[0].lower()) or "paper"
    if first_word in {"a", "an", "the", "do"} and len(p["title"].split()) > 1:
        first_word = re.sub(r"[^a-z]", "", p["title"].split()[1].lower())
    key = f'{last}{p["year"]}{first_word}'
    authors = " and ".join([SITE["name"]] + p["coauthors"])
    if p["status"] == "published":
        lines = ["@article{" + key, f"  author = {{{authors}}}", f"  title = {{{p['title']}}}",
                 f"  journal = {{{p.get('venue', '')}}}", f"  year = {{{p['year']}}}"]
    else:
        note = "Working paper" + ("; " + p["note"][0].lower() + p["note"][1:] if p.get("note") else "")
        lines = ["@unpublished{" + key, f"  author = {{{authors}}}", f"  title = {{{p['title']}}}",
                 f"  year = {{{p['year']}}}", f"  note = {{{note}}}"]
    if p.get("ssrn"):
        lines.append(f"  url = {{{p['ssrn']}}}")
    return ",\n".join(lines) + "\n}"


def has_page(p):
    """Paper pages exist only where there is something beyond the card."""
    return bool(p.get("abstract") or p.get("presentations"))


def page(title, body, active="", prefix="", description="", canonical=""):
    cur = ' class="active" aria-current="page"'
    nav = "\n".join(
        f'<a href="{prefix}{href}"{cur if href == active else ""}>{label}</a>'
        for href, label in NAV)
    desc = e(description or f'{SITE["name"]}, {SITE["title"]}, {SITE["affiliation"]}.')
    canon = SITE["domain"].rstrip("/") + "/" + canonical
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
<meta name="color-scheme" content="light dark">
<link rel="icon" type="image/svg+xml" href="{prefix}assets/favicon.svg">
<link rel="alternate" type="application/atom+xml" title="{e(SITE['name'])}: Research" href="{prefix}feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="{prefix}assets/site.css">
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


def active_links():
    out = []
    for l in SITE["links"]:
        if not l["url"]:
            continue
        # A local file that is not there yet (e.g. the CV PDF) falls back to cv.html.
        if not l["url"].startswith(("http", "mailto:")) and not (ROOT / l["url"]).exists():
            l = dict(l, url="cv.html")
        out.append(l)
    return out


def link_tag(l):
    ext = ' target="_blank" rel="noopener"' if l["url"].startswith("http") else ""
    return f'<a href="{e(l["url"])}"{ext}>{e(l["label"])}</a>'


# ── Home ─────────────────────────────────────────────────────────────
def build_home():
    if SITE.get("photo"):
        photo = f'<img src="{e(SITE["photo"])}" alt="{e(SITE["name"])}" width="520" height="650">'
    else:
        initials = "".join(w[0] for w in SITE["name"].split())
        photo = f'<div class="monogram" aria-hidden="true">{initials}</div>'

    news = []
    for n in SITE["news"]:
        p = BY_SLUG.get(n.get("paper", ""))
        if p:
            href = f'papers/{p["slug"]}.html' if has_page(p) else "research.html#" + p["slug"]
            title = f'<a href="{href}">{e(p["title"])}</a>'
            meta = (authors_line(p) + " &middot; " if p["coauthors"] else "") + f'<em>{e(n["meta"])}</em>'
        else:
            title = e(n["title"])
            meta = e(n["meta"])
        news.append(f"""      <div class="announce-item">
        <span class="announce-tag">{e(n['tag'])}</span>
        <div><div class="announce-title">{title}</div><div class="announce-meta">{meta}</div></div>
      </div>""")

    about = "\n".join(f"<p>{para}</p>" for para in SITE["about"])
    edu = "\n".join(f'<li><div class="primary">{e(x["degree"])}</div><div class="secondary">{e(x["school"])}</div></li>'
                    for x in SITE["education"])
    rail = lambda items: "\n".join(f"<li>{x}</li>" for x in items)

    sameas = [l["url"] for l in active_links() if l["url"].startswith("http")]
    ld = {"@context": "https://schema.org", "@type": "Person", "name": SITE["name"],
          "url": SITE["domain"] + "/", "jobTitle": SITE["title"], "email": "mailto:" + SITE["email"],
          "affiliation": {"@type": "Organization", "name": SITE["affiliation"]}}
    if sameas:
        ld["sameAs"] = sameas

    body = f"""<script type="application/ld+json">{json.dumps(ld)}</script>
<section class="hero">
  <div class="wrap">
    <div>
      <h1>{e(SITE['name'])}</h1>
      <p class="hero-role">{e(SITE['title'])}, <a href="{e(SITE['affiliation_url'])}" target="_blank" rel="noopener">{e(SITE['affiliation'])}</a></p>
      <p class="hero-lede">{e(SITE['lede'])}</p>
      <div class="hero-links">
        {' '.join(link_tag(l) for l in active_links())}
      </div>
    </div>
    <div class="hero-photo">{photo}</div>
  </div>
</section>

<div class="announce">
  <div class="wrap announce-stack">
    <div class="announce-heading">Latest Updates &middot; <a href="feed.xml">RSS</a></div>
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
      <div class="rail-block"><div class="rail-heading">Research</div><div class="rail-note">{sum(p['status'] != 'published' for p in PAPERS)} current papers on voluntary and mandatory disclosure, analysts, and research methods.<br><a href="research.html">See all papers &rarr;</a></div></div>
      <div class="rail-block"><div class="rail-heading">Selected Honors</div><ul class="rail-list">{rail(e(x) for x in SITE['awards'])}</ul></div>
      <div class="rail-block"><div class="rail-heading">Service</div><ul class="rail-list">{rail(SITE['service'])}</ul></div>
      <div class="rail-block"><div class="rail-heading">Contact</div><div class="rail-note"><a href="mailto:{e(SITE['email'])}">{e(SITE['email'])}</a><br>{'<br>'.join(e(x) for x in SITE['address'])}</div></div>
    </aside>
  </div>
</main>"""
    return page(f'{SITE["name"]}, {SITE["affiliation"]}', body, "index.html",
                description=f'{SITE["name"]} is an {SITE["title"]} at the {SITE["affiliation"]}. {SITE["lede"]}')


# ── Research ─────────────────────────────────────────────────────────
def paper_card(p):
    title_html = (f'<a href="papers/{p["slug"]}.html">{e(p["title"])}</a>' if has_page(p) else e(p["title"]))
    note = f'<p class="paper-note">{e(p["note"])}</p>' if p.get("note") else ""
    if p["status"] == "published" and p.get("cite"):
        note = f'<p class="paper-authors"><em>{e(p["venue"])}</em>, {p["year"]}, {e(p["cite"])}</p>'
    abstract = (f'<details class="paper-abstract"><summary>Abstract</summary><p>{e(p["abstract"])}</p></details>'
                if p.get("abstract") else "")
    links = links_for(p)
    if has_page(p):
        links.insert(0, f'<a href="papers/{p["slug"]}.html">Paper Page</a>')
    links.append(f'<button type="button" class="bib-btn" data-bib="{p["slug"]}">BibTeX</button>')
    search = " ".join([p["title"], " ".join(p["coauthors"]), p.get("note", ""), p.get("venue", ""),
                       STATUS_LABEL[p["status"]], THEMES.get(p["theme"], ""), p.get("abstract", "")]).lower()
    return f"""<article class="paper" id="{p['slug']}" data-status="{p['status']}" data-search="{e(search)}">
  <div class="paper-head">{f'<span class="paper-kicker">{e(kicker(p))}</span>' if kicker(p) else ""}<span class="status-pill status-{p['status']}">{STATUS_LABEL[p['status']]}</span></div>
  <h3>{title_html}</h3>
  {f'<p class="paper-authors">{e(authors_line(p))}</p>' if p["coauthors"] else ""}
  {note}
  {abstract}
  <div class="entry-links">{' '.join(links)}</div>
  <script type="text/x-bibtex" id="bib-{p['slug']}">{e(bibtex(p))}</script>
</article>"""


def build_research():
    groups = []
    for key, label in THEMES.items():
        ps = [p for p in PAPERS if p["theme"] == key]
        if ps:
            groups.append(f'<section class="theme-group"><h2>{e(label)}</h2>\n'
                          + "\n".join(paper_card(p) for p in ps) + "</section>")
    counts = {s: sum(p["status"] == s for p in PAPERS) for s in STATUS_LABEL}
    chips = [f'<button type="button" class="chip" data-status="all" aria-pressed="true">All<span class="chip-n">{len(PAPERS)}</span></button>']
    chips += [f'<button type="button" class="chip" data-status="{s}" aria-pressed="false">{STATUS_LABEL[s]}<span class="chip-n">{n}</span></button>'
              for s, n in counts.items() if n]
    body = f"""<div class="page-head"><div class="wrap">
  <h1>Research</h1>
  <p>My research examines corporate voluntary and mandatory disclosures, financial analysts, disclosure regulation, and their implications for capital markets.</p>
</div></div>
<main id="main" tabindex="-1" class="main" style="padding-top:0">
  <div class="wrap">
    <div class="toolbar">
      <label class="visually-hidden" for="rt-search">Search papers</label>
      <input id="rt-search" class="rt-search" type="search" placeholder="Search titles, coauthors, abstracts&hellip;">
      <div class="chips" role="group" aria-label="Filter by status">{''.join(chips)}</div>
      <span id="rt-count" class="rt-count" aria-live="polite"></span>
    </div>
    <div id="paper-list">
{chr(10).join(groups)}
      <p id="rt-empty" class="empty-state" hidden>No papers match that search.</p>
    </div>
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
    links = links_for(p, "../")
    links.append(f'<button type="button" class="bib-btn" data-bib="{p["slug"]}">Copy BibTeX</button>')
    body = f"""<main id="main" tabindex="-1" class="paper-page">
  <div class="wrap">
    <a class="crumb" href="../research.html">&larr; All research</a>
    <div class="paper-head">{f'<span class="paper-kicker">{e(kicker(p))}</span>' if kicker(p) else ""}<span class="status-pill status-{p['status']}">{STATUS_LABEL[p['status']]}</span></div>
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
    body = f"""<div class="page-head"><div class="wrap"><h1>Teaching</h1>
  <p>Course ratings are student evaluations on a five-point scale.</p></div></div>
<main id="main" tabindex="-1" class="main">
  <div class="wrap cols">
    <div>{''.join(groups)}</div>
    <aside><div class="rail-block"><div class="rail-heading">Teaching Development</div><ul class="rail-list">{notes}</ul></div></aside>
  </div>
</main>"""
    return page(f'Teaching | {SITE["name"]}', body, "teaching.html", canonical="teaching.html")


# ── CV ───────────────────────────────────────────────────────────────
def build_cv():
    cv_link = next((l["url"] for l in SITE["links"] if l["label"] == "Curriculum Vitae" and l["url"]), "")
    cv_pdf_exists = cv_link and (ROOT / cv_link).exists()
    cta = (f'<a class="cv-cta" href="{e(cv_link)}" target="_blank" rel="noopener">Download CV (PDF)</a>'
           if cv_pdf_exists else "")
    edu = "".join(f'<li><span>{e(x["degree"])}, {e(x["school"])}</span></li>' for x in SITE["education"])
    cur = [p for p in PAPERS if p["status"] != "published"]
    pre = [p for p in PAPERS if p["status"] == "published"]
    cur_li = "".join(f'<li><span>&ldquo;{e(p["title"])}&rdquo;{(", " + e(authors_line(p))) if p["coauthors"] else ""}'
                     f'{(" &middot; <em>" + e(p["note"]) + "</em>") if p.get("note") else ""}</span></li>' for p in cur)
    pre_li = "".join(f'<li><span>&ldquo;{e(p["title"])}&rdquo;, {e(authors_line(p))}, <em>{e(p["venue"])}</em></span>'
                     f'<span class="d">{p["year"]}</span></li>' for p in pre)
    body = f"""<div class="page-head"><div class="wrap"><h1>Curriculum Vitae</h1>
  <p>A summary of my CV. The PDF has the full record of presentations, service, and honors.</p>{cta}</div></div>
<main id="main" tabindex="-1" class="main">
  <div class="wrap" style="max-width:860px">
    <div class="block"><h2 class="section-label">Academic Employment</h2><ul class="dated-list">
      <li><span>{e(SITE['title'])}, {e(SITE['affiliation'])}</span><span class="d">2025&ndash;present</span></li></ul></div>
    <div class="block"><h2 class="section-label">Education</h2><ul class="dated-list">{edu}</ul></div>
    <div class="block"><h2 class="section-label">Working Papers</h2><ul class="dated-list">{cur_li}</ul></div>
    <div class="block"><h2 class="section-label">Pre-Doctoral Publications</h2><ul class="dated-list">{pre_li}</ul></div>
    <div class="block"><h2 class="section-label">Honors</h2><ul class="dated-list">{''.join(f'<li><span>{e(x)}</span></li>' for x in SITE['awards'])}</ul></div>
    <div class="block"><h2 class="section-label">Service</h2><ul class="dated-list">{''.join(f'<li><span>{x}</span></li>' for x in SITE['service'])}</ul></div>
  </div>
</main>"""
    return page(f'CV | {SITE["name"]}', body, "cv.html", canonical="cv.html")


# ── Feed + sitemap ───────────────────────────────────────────────────
def build_feed():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = SITE["domain"].rstrip("/")
    entries = []
    for p in [p for p in PAPERS if p["status"] != "published"]:
        url = f'{base}/papers/{p["slug"]}.html' if has_page(p) else f'{base}/research.html#{p["slug"]}'
        entries.append(f"""  <entry><title>{e(p['title'])}</title><link href="{url}"/><id>{url}</id><updated>{now}</updated>
    <summary>{e(authors_line(p) + ('. ' + p['note'] if p.get('note') else '') + '. ' + STATUS_LABEL[p['status']])}</summary></entry>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{e(SITE['name'])}: Research</title>
  <link href="{base}/"/><link rel="self" href="{base}/feed.xml"/>
  <id>{base}/</id><updated>{now}</updated><author><name>{e(SITE['name'])}</name></author>
{chr(10).join(entries)}
</feed>
"""


def build_sitemap(paths):
    base = SITE["domain"].rstrip("/")
    urls = "\n".join(f"  <url><loc>{base}/{'' if p == 'index.html' else p}</loc></url>" for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n'


def main():
    out = {"index.html": build_home(), "research.html": build_research(),
           "teaching.html": build_teaching(), "cv.html": build_cv()}
    papers_dir = ROOT / "papers"
    papers_dir.mkdir(exist_ok=True)
    for old in papers_dir.glob("*.html"):
        old.unlink()
    for p in PAPERS:
        if has_page(p):
            out[f'papers/{p["slug"]}.html'] = build_paper_page(p)
    out["feed.xml"] = build_feed()
    out["sitemap.xml"] = build_sitemap([k for k in out if k.endswith(".html")])
    for path, text in out.items():
        (ROOT / path).write_text(text)
    print(f"Built {len(out)} files.")


if __name__ == "__main__":
    main()
