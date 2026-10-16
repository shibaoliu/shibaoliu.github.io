#!/usr/bin/env python3
"""Step 6: find a link to each public R&R paper (the title on the AcctRes page links to it).

Route, first hit wins:
  1. the author's own source page (HTML): an anchor whose text is the title (similarity >= 0.85), or the first
     paper-like anchor (SSRN / DOI / PDF / "paper" / "draft" / "link") within 400 characters after the title;
  2. Crossref posted-content (SSRN): a record whose title matches (similarity >= 0.93) and whose authors include
     the listing author's family name -> https://doi.org/<doi>.
No link is better than a wrong one: entries without a hit stay unlinked.
Input/Output: data/rr_public.json (adds paper_url, paper_url_source per entry); log: logs/06_links.log
"""
import difflib, json, os, re, sys, unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
scan = importlib.import_module("03_scan")
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "data", "rr_public.json")


def nz(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


class Pos(HTMLParser):
    """Collect page text and every anchor with its character offset in that text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.anchors, self._a, self.skip = "", [], None, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "a":
            self._a = [dict(attrs).get("href") or "", len(self.text), ""]

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag == "a" and self._a:
            self.anchors.append(tuple(self._a)); self._a = None
        self.text += " "

    def handle_data(self, d):
        if self.skip:
            return
        self.text += d
        if self._a is not None:
            self._a[2] += d


PAPERY = re.compile(r"ssrn|doi\.org|\.pdf($|\?)|papers?|draft|download|link|arxiv|nber\.org/papers", re.I)
BAD = re.compile(r"mailto:|javascript:|scholar\.google|linkedin|twitter|x\.com/|slides|appendix|video|podcast|news", re.I)
_page_cache = {}


def page(url):
    if url not in _page_cache:
        _page_cache[url] = None
        try:
            if scan.allowed(url):
                r = scan.polite_get(url)
                ctype = r.headers.get("Content-Type", "").lower()
                if r.status_code == 200 and "html" in ctype:
                    p = Pos(); p.feed(r.text); p.final = r.url
                    _page_cache[url] = p
        except Exception:
            pass
    return _page_cache[url]


def ssrn_stable(u):
    """Time-limited download.ssrn.com links expire; use the abstract page instead."""
    m = re.search(r"ssrn\.com/.*?(?:abstract_?id=|/)(\d{6,8})", u)
    if m and "download.ssrn.com" in u:
        return "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=" + m.group(1)
    return u


def from_page(url, title):
    p = page(url)
    if not p:
        return ""
    t = nz(title)
    for href, _, txt in p.anchors:
        if href and not BAD.search(href) and len(nz(txt)) > 10 and \
                difflib.SequenceMatcher(None, nz(txt), t).ratio() >= 0.85:
            return ssrn_stable(urljoin(p.final, href))
    # A "nearest paper-like link after the title" rule was tried on 2026-10-16 and an independent check found it
    # picked the NEXT paper's link in 5 of 59 cases, so only an anchor whose own text is the title is used.
    return ""


def norm_map(s):
    """nz()-style normalisation that also returns, for each output character, its offset in s."""
    out, idx, prev_sp = [], [], True
    for i, ch in enumerate(s):
        c = unicodedata.normalize("NFKD", ch)
        c = "".join(x for x in c if not unicodedata.combining(x)).lower()[:1]
        c = c if c and c.isalnum() else " "
        if c == " " and prev_sp:
            continue
        out.append(c); idx.append(i); prev_sp = c == " "
    return "".join(out), idx


def from_crossref(title, author):
    fam = nz(author).split()[-1]
    r = requests.get("https://api.crossref.org/works",
                     params={"query.bibliographic": title, "rows": 6, "filter": "type:posted-content",
                             "select": "DOI,title,author", "mailto": "tanglin817@gmail.com"},
                     headers={"User-Agent": scan.UA}, timeout=30)
    r.raise_for_status()
    for it in r.json()["message"]["items"]:
        t = (it.get("title") or [""])[0]
        fams = {nz(a.get("family", "")).split()[-1] for a in it.get("author", []) if nz(a.get("family", ""))}
        if difflib.SequenceMatcher(None, nz(t), nz(title)).ratio() >= 0.93 and fam in fams:
            return "https://doi.org/" + it["DOI"]
    return ""


def main():
    d = json.load(open(P))
    n_page = n_cr = 0
    for x in d["entries"]:
        x["paper_url"], x["paper_url_source"] = "", ""
        for au in x["authors"]:
            u = from_page(au["source_url"], x["title"])
            if u:
                x["paper_url"], x["paper_url_source"] = u, "author page: " + au["source_url"]
                n_page += 1
                break
        if not x["paper_url"]:
            for au in x["authors"]:
                try:
                    u = from_crossref(x["title"], au["name"])
                except Exception as e:
                    print("crossref error", type(e).__name__, x["title"][:50]); u = ""
                if u:
                    x["paper_url"], x["paper_url_source"] = u, "crossref posted-content"
                    n_cr += 1
                    break
        print("%-10s %-70s %s" % (x["paper_url_source"][:10] or "-", x["title"][:70], x["paper_url"]), flush=True)
    json.dump(d, open(P, "w"), indent=1, ensure_ascii=False)
    print("entries %d; linked from author page %d; via Crossref/SSRN %d; unlinked %d"
          % (len(d["entries"]), n_page, n_cr, len(d["entries"]) - n_page - n_cr))


if __name__ == "__main__":
    main()
