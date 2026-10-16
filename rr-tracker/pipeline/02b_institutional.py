#!/usr/bin/env python3
"""Step 2b: institutional-profile discovery via sitemaps (no search engines). Accounting-5 cohort only.

Route: OpenAlex author -> last-known institution -> OpenAlex institution homepage_url ->
       robots.txt Sitemap: lines (else /sitemap.xml) -> expand sitemap indexes (bounded) ->
       URLs whose path contains a name slug of the author (first-last, last-first, firstlast, first_last, first.last) ->
       fetch candidate page (robots.txt checked) and keep it only if its <title> contains the author's
       first and last name tokens.

Scope: institutions ranked by number of accounting-5 authors; TOP_N institutions (argv[1], default 40).
Outputs: data/homepages_institutional.csv, data/institution_sitemap_status.csv
"""
import csv, gzip, io, os, re, sys, time, threading, unicodedata, urllib.robotparser
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin
import requests
import urllib3
urllib3.disable_warnings()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = "shibaoliu.github.io RR tracker (contact: tanglin817@gmail.com)"
TOP_N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
MAX_SITEMAPS = 80          # per institution
MAX_BYTES = 60_000_000     # per institution
TIMEOUT = 15

_host_last = defaultdict(float)
_host_lock = defaultdict(threading.Lock)
_robots = {}
_robots_lock = threading.Lock()


def norm_tokens(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s.replace("-", " ")).split()


def polite_get(url, **kw):
    host = urlparse(url).netloc
    with _host_lock[host]:
        wait = 1.0 - (time.time() - _host_last[host])
        if wait > 0:
            time.sleep(wait)
        try:
            return requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, **kw)
        finally:
            _host_last[host] = time.time()


def robots_for(url):
    p = urlparse(url)
    base = "%s://%s" % (p.scheme, p.netloc)
    with _robots_lock:
        if base in _robots:
            return _robots[base]
    rp = urllib.robotparser.RobotFileParser()
    sitemaps = []
    try:
        r = polite_get(base + "/robots.txt")
        if r.status_code == 200:
            lines = r.text.splitlines()
            rp.parse(lines)
            sitemaps = [l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("sitemap:")]
        elif r.status_code in (401, 403):
            rp.disallow_all = True
        else:
            rp.allow_all = True
    except Exception:
        rp.allow_all = True
    with _robots_lock:
        _robots[base] = (rp, sitemaps)
    return rp, sitemaps


def allowed(url):
    rp, _ = robots_for(url)
    return rp.can_fetch(UA, url)


def fetch_sitemap(url):
    if not allowed(url):
        return None, "robots-disallow"
    try:
        r = polite_get(url)
    except Exception as e:
        return None, "err:%s" % type(e).__name__
    if r.status_code != 200:
        return None, "http%d" % r.status_code
    body = r.content
    if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except Exception:
            pass
    return body, "ok"


LOC = re.compile(rb"<loc>\s*(.*?)\s*</loc>", re.S | re.I)


def crawl_institution(inst):
    """Return (set of page URLs, status dict)."""
    home = inst["homepage_url"]
    st = dict(institution_id=inst["institution_id"], display_name=inst["display_name"], homepage_url=home,
              sitemaps_fetched=0, bytes=0, page_urls=0, status="")
    if not home:
        st["status"] = "no-homepage"; return set(), st
    p = urlparse(home if "://" in home else "https://" + home)
    base = "https://%s" % p.netloc
    _, sms = robots_for(base + "/")
    queue = list(sms) or [base + "/sitemap.xml", base + "/sitemap_index.xml"]
    seen, pages = set(), set()
    first_status = None
    while queue and st["sitemaps_fetched"] < MAX_SITEMAPS and st["bytes"] < MAX_BYTES:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        body, s = fetch_sitemap(sm)
        first_status = first_status or s
        st["sitemaps_fetched"] += 1
        if body is None:
            continue
        st["bytes"] += len(body)
        locs = [l.decode("utf-8", "ignore").replace("&amp;", "&") for l in LOC.findall(body)]
        if b"<sitemapindex" in body[:2000].lower() or b"<sitemapindex" in body.lower()[:5000]:
            # prioritise child sitemaps that look like people/profile/faculty listings
            pri = [l for l in locs if re.search(r"people|person|profile|faculty|staff|directory|expert|user", l, re.I)]
            queue = pri + queue + [l for l in locs if l not in pri]
        else:
            pages.update(locs)
    st["page_urls"] = len(pages)
    st["status"] = "ok" if pages else ("no-sitemap(%s)" % first_status)
    return pages, st


def slugs(name):
    t = norm_tokens(name)
    if len(t) < 2:
        return []
    f, l = t[0], t[-1]
    return [f + "-" + l, l + "-" + f, f + "_" + l, f + "." + l, f + l, l + "-" + f]


def title_ok(url, name):
    if not allowed(url):
        return False, "robots-disallow", ""
    try:
        r = polite_get(url)
    except Exception as e:
        return False, "err:%s" % type(e).__name__, ""
    if r.status_code != 200:
        return False, "http%d" % r.status_code, ""
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    tt = set(norm_tokens(title))
    t = norm_tokens(name)
    ok = bool(t) and t[0] in tt and t[-1] in tt
    return ok, "ok", title[:200]


def main():
    t0 = time.time()
    authors = [a for a in csv.DictReader(open(os.path.join(DATA, "cohort_authors.csv"))) if a["acc5_flag"] == "1"]
    insts = {r["institution_id"]: r for r in csv.DictReader(open(os.path.join(DATA, "institutions.csv")))}
    by_inst = defaultdict(list)
    for a in authors:
        ids = (a["last_known_institution_ids"] or a["latest_paper_institution_ids"]).split("|")
        if ids[0]:
            by_inst[ids[0]].append(a)
    ranked = sorted(by_inst, key=lambda i: -len(by_inst[i]))[:TOP_N]
    covered_authors = sum(len(by_inst[i]) for i in ranked)
    print("accounting-5 authors %d; institutions %d; testing top %d institutions covering %d authors"
          % (len(authors), len(by_inst), len(ranked), covered_authors), flush=True)

    def work(iid):
        inst = insts.get(iid, {"institution_id": iid, "display_name": "", "homepage_url": ""})
        pages, st = crawl_institution(inst)
        found = []
        low = [(u, urlparse(u).path.lower()) for u in pages]
        for a in by_inst[iid]:
            ss = slugs(a["display_name"])
            cands = [u for u, path in low if any(re.search(r"(^|[/=])" + re.escape(s) + r"($|[/.?#-])", path) for s in ss)]
            for u in cands[:3]:
                ok, s, title = title_ok(u, a["display_name"])
                found.append(dict(author_id=a["author_id"], display_name=a["display_name"], institution=inst["display_name"],
                                  url=u, source="institution-sitemap:" + (inst["homepage_url"] or ""),
                                  page_title=title, title_has_name=int(ok), fetch_status=s))
        st["authors"] = len(by_inst[iid])
        st["authors_matched"] = len({f["author_id"] for f in found if f["title_has_name"]})
        print("  %-45s %-8s sitemaps=%3d pages=%7d authors=%3d matched=%3d %.0fs" % (
            inst["display_name"][:45], st["status"][:8], st["sitemaps_fetched"], st["page_urls"], st["authors"],
            st["authors_matched"], time.time() - t0), flush=True)
        return found, st

    allfound, allst = [], []
    with ThreadPoolExecutor(8) as ex:
        for found, st in ex.map(work, ranked):
            allfound += found; allst.append(st)
    with open(os.path.join(DATA, "homepages_institutional.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["author_id", "display_name", "institution", "url", "source", "page_title",
                                          "title_has_name", "fetch_status"])
        w.writeheader(); w.writerows(allfound)
    with open(os.path.join(DATA, "institution_sitemap_status.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allst[0].keys()))
        w.writeheader(); w.writerows(allst)
    matched = {f["author_id"] for f in allfound if f["title_has_name"]}
    print("institution status:", Counter(s["status"].split("(")[0] for s in allst))
    print("authors at tested institutions: %d; with verified institutional page: %d (%.1f%%)"
          % (covered_authors, len(matched), 100 * len(matched) / max(covered_authors, 1)))
    print("runtime %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
