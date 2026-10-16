#!/usr/bin/env python3
"""Step 2c: curated faculty-directory route (accounting-5 cohort only).

Input : data/directories/faculty_directories.csv (one row per school: institution_id, directory_url,
        render, profile_url_example ...), built once by hand-checked agent search and spot-checked.
Route : directory page -> anchors whose text (or URL slug) carries the author's first AND last name
        -> that profile page -> links on the profile that point to a personal site or a CV PDF.
        For schools whose directory is rendered by JavaScript or blocked, a profile URL is tried only by
        substituting the author's name into the example profile URL's slug; the page is accepted only if
        it returns 200 and its <title> or <h1> carries both name tokens.
Output: data/homepages_directory.csv  (author_id, display_name, url, url_kind, profile_url, source)
        data/directory_status.csv     (per school: status, authors at school, authors matched)
robots.txt honoured, >= 1 s between requests to the same host, same User-Agent as step 3.
"""
import csv, os, re, sys, time, unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
scan = importlib.import_module("03_scan")  # reuse polite_get / allowed / SKIP_HOSTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def name_tokens(display):
    t = [x for x in fold(display).split() if len(x) > 1]
    if len(t) < 2:
        return None
    return t[0], t[-1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._a, self.title, self._t, self.h1, self._h = [], None, "", False, "", False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._a = [dict(attrs).get("href") or "", []]
        elif tag == "title":
            self._t = True
        elif tag == "h1":
            self._h = True

    def handle_endtag(self, tag):
        if tag == "a" and self._a:
            self.links.append((self._a[0], " ".join(self._a[1]).strip()))
            self._a = None
        elif tag == "title":
            self._t = False
        elif tag == "h1":
            self._h = False

    def handle_data(self, d):
        if self._a is not None:
            self._a[1].append(d)
        if self._t:
            self.title += d
        if self._h:
            self.h1 += d


def get(url):
    if not scan.allowed(url):
        return None, "robots-disallow"
    try:
        r = scan.polite_get(url)
    except Exception as e:
        return None, "err:%s" % type(e).__name__
    if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "html").lower():
        return None, "http%d" % r.status_code
    p = Links()
    try:
        p.feed(r.text)
    except Exception:
        pass
    p.final = r.url
    return p, "ok"


def has_name(text, first, last):
    w = set(fold(text).split())
    return last in w and (first in w or any(x == first[0] for x in w))


PERSONAL_TXT = re.compile(r"personal (web)?site|personal (home ?page|page)|home ?page|web ?site|^website$|"
                          r"curriculum vitae|\bcv\b|\bvita\b|research (web)?site|my site", re.I)


NEWSY = re.compile(r"/(news|insights?|stories|events?|press|magazine|blog)/", re.I)


def name_in_url(u, first, last):
    f = fold(urlparse(u).netloc + " " + urlparse(u).path)
    squash = f.replace(" ", "")
    return last in f.split() or (first + last) in squash or (last + first) in squash


def outlinks(profile, first, last):
    """Links on a profile page that plausibly lead to the person's own site or CV."""
    out, host = [], urlparse(profile.final).netloc
    for h, t in profile.links:
        if not h or h.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        u = urldefrag(urljoin(profile.final, h))[0]
        pu = urlparse(u)
        if pu.scheme not in ("http", "https") or scan.SKIP_HOSTS.search(pu.netloc + pu.path):
            continue
        path = pu.path.lower()
        slug = fold(pu.netloc + " " + pu.path)
        if path.endswith(".pdf") and re.search(r"(^|[/_.-])(cv|vita|curriculum|resume)", path):
            out.append((u, "cv"))
        elif pu.netloc != host and name_in_url(u, first, last) and not NEWSY.search(pu.path):
            # a personal site must carry the person's name in its URL; anchor text such as "Website" alone
            # also matched footer links (privacy notices, alumni pages) in the first run
            out.append((u, "personal"))
    seen, res = set(), []
    for u, k in out:
        if u not in seen:
            seen.add(u); res.append((u, k))
    return res[:3]


def slug_variants(example, first, last):
    """Substitute the author's name into the last path segment of an example profile URL."""
    pu = urlparse(example)
    segs = pu.path.rstrip("/").split("/")
    if not segs or not segs[-1]:
        return []
    ex = segs[-1]
    sep = "-" if "-" in ex else ("_" if "_" in ex else ("." if "." in ex else ""))
    ext = ""
    m = re.search(r"(\.(?:html?|aspx|php))$", ex)
    if m:
        ext = m.group(1)
    forms = {first + sep + last, last + sep + first} if sep else {first + last, last + first}
    trail = "/" if pu.path.endswith("/") else ""
    return ["%s://%s%s/%s%s%s" % (pu.scheme, pu.netloc, "/".join(segs[:-1]), f, ext, trail) for f in sorted(forms)]


def run_school(row, people):
    status, found = "", []
    d = row["directory_url"].strip()
    tried_dir = False
    if d and row.get("render") in ("static", ""):
        tried_dir = True
        page, status = get(d)
        if page:
            for a in people:
                nt = name_tokens(a["display_name"])
                if not nt:
                    continue
                first, last = nt
                for h, t in page.links:
                    u = urldefrag(urljoin(page.final, h))[0]
                    if len(t) <= 80 and (has_name(t, first, last) or
                                         (last in fold(urlparse(u).path).split() and first in fold(urlparse(u).path).split())):
                        if urlparse(u).scheme in ("http", "https"):
                            found.append((a, u)); break
    matched = {a["author_id"] for a, _ in found}
    ex = row.get("profile_url_example", "").strip()
    if ex.startswith("http"):
        for a in people:
            if a["author_id"] in matched:
                continue
            nt = name_tokens(a["display_name"])
            if not nt:
                continue
            for u in slug_variants(ex, *nt):
                p, st = get(u)
                if p and has_name(p.title + " " + p.h1, *nt):
                    found.append((a, p.final)); break
        if not tried_dir:
            status = "slug-route"
    rows = []
    for a, prof in found:
        nt = name_tokens(a["display_name"])
        p, st = get(prof)
        if not p:
            continue
        # the profile must actually be this person's page
        if not has_name(p.title + " " + p.h1, *nt):
            continue
        src = "directory:%s" % (d or ex)
        rows.append(dict(author_id=a["author_id"], display_name=a["display_name"], url=p.final,
                         url_kind="profile", profile_url=p.final, source=src))
        for u, k in outlinks(p, *nt):
            rows.append(dict(author_id=a["author_id"], display_name=a["display_name"], url=u,
                             url_kind=k, profile_url=p.final, source=src))
    return dict(institution_id=row["institution_id"], display_name=row["display_name"], directory_url=d,
                render=row.get("render", ""), status=status or "no-directory", n_authors=len(people),
                n_matched=len({r["author_id"] for r in rows})), rows


def main():
    t0 = time.time()
    authors = [a for a in csv.DictReader(open(os.path.join(DATA, "cohort_authors.csv"))) if a["acc5_flag"] == "1"]
    by_inst = defaultdict(list)
    for a in authors:
        i = (a["last_known_institution_ids"] or a["latest_paper_institution_ids"]).split("|")[0]
        by_inst[i].append(a)
    schools = list(csv.DictReader(open(os.path.join(DATA, "directories", "faculty_directories.csv"))))
    stat, out = [], []
    with ThreadPoolExecutor(12) as ex:
        for s, rows in ex.map(lambda r: run_school(r, by_inst.get(r["institution_id"], [])), schools):
            stat.append(s); out += rows
            print("%-55s %-14s %3d/%3d" % (s["display_name"][:55], s["status"], s["n_matched"], s["n_authors"]), flush=True)
    with open(os.path.join(DATA, "homepages_directory.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["author_id", "display_name", "url", "url_kind", "profile_url", "source"])
        w.writeheader(); w.writerows(out)
    with open(os.path.join(DATA, "directory_status.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(stat[0]))
        w.writeheader(); w.writerows(stat)
    n_at = sum(s["n_authors"] for s in stat)
    n_m = len({r["author_id"] for r in out})
    print("schools %d; accounting-5 authors at these schools %d; matched to a profile %d" % (len(stat), n_at, n_m))
    print("by kind:", {k: sum(r["url_kind"] == k for r in out) for k in ("profile", "personal", "cv")})
    print("runtime %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
