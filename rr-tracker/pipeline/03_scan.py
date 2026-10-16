#!/usr/bin/env python3
"""Step 3: R&R scan prototype.

Input : data/homepages_orcid.csv (name_match != 'no') and data/homepages_institutional.csv (title_has_name == 1)
Sample: up to MAX_AUTHORS (argv[1], default 150) authors with >=1 crawlable URL, accounting-5 cohort,
        drawn with a fixed random seed (so the yield estimate is not cherry-picked).
Crawl : each start URL + at most 2 same-host links whose anchor text/href matches research|papers|working|cv
        (PDF links followed only if the file name matches cv|vita; text via pdftotext).
        robots.txt honoured (urllib.robotparser), >= 1 s between requests to the same host, 15 s timeout,
        User-Agent "shibaoliu.github.io RR tracker (contact: tanglin817@gmail.com)".
Match : status phrase within ~200 chars of a journal name/abbreviation.
Output: data/rr_candidates.json, data/scan_fetch_log.csv
Nothing is inferred beyond the page text: every candidate carries source_url + verbatim snippet (<=300 chars).
"""
import csv, datetime, html, json, os, random, re, subprocess, sys, tempfile, threading, time, urllib.robotparser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag
import requests
import urllib3
urllib3.disable_warnings()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = "shibaoliu.github.io RR tracker (contact: tanglin817@gmail.com)"
MAX_AUTHORS = int(sys.argv[1]) if len(sys.argv) > 1 else 150  # 0 = every eligible author
SEED = 20261015
TIMEOUT = 15
TODAY = datetime.date.today().isoformat()

# hosts that are not author-maintained pages, are search engines, or forbid/bot-block crawling
SKIP_HOSTS = re.compile(r"(linkedin\.com|twitter\.com|(^|\.)x\.com|facebook\.com|instagram\.com|scholar\.google|"
                        r"ssrn\.com|researchgate\.net|orcid\.org|scopus\.com|publons\.com|webofscience\.com|"
                        r"youtube\.com|semanticscholar\.org|academia\.edu|mendeley\.com|loop\.frontiersin|"
                        r"researcherid\.com|github\.com|wikipedia\.org|bsky\.app|dblp\.org|ideas\.repec|"
                        r"econpapers|google\.com/citations)", re.I)

STATUS = re.compile(r"(revise\s*(?:and|&)\s*resubmit(?:ted)?|revise-and-resubmit|\bR\s?&\s?R\b|revision\s+requested|"
                    r"second[- ]round|2nd[- ]round|resubmitted)", re.I)
JOURNALS = [  # (code, regex) ; abbreviations are case-sensitive word matches
    ("JAE", r"Journal of Accounting (?:and|&) Economics|\bJAE\b"),
    ("JAR", r"Journal of Accounting Research|\bJAR\b"),
    ("TAR", r"(?<!European )(?<!British )(?<!Asian )(?<!International )(?<!Pacific )(?<!China )(?<!Japanese )(?<!Abacus )(?:The )?Accounting Review|\bTAR\b"),
    ("CAR", r"Contemporary Accounting Research|\bCAR\b"),
    ("RAST", r"Review of Accounting Studies|\bRAST\b|\bRAS\b"),
    ("MS", r"Management Science|\bMS\b|\bMgmt\.? Sci"),
]
JRE = [(c, re.compile(p)) for c, p in JOURNALS]
JANY = re.compile("|".join("(?:%s)" % p for _, p in JOURNALS))
FWD_GAP = re.compile(r"^[\s,:;.\-–—(\[|]*(?:\([^)]{0,30}\)\s*)?(?:(?:now|currently|under review)\s+)?"
                     r"(?:(?:at|from|in|with|to|for|by)\s+)?(?:the\s+)?$", re.I)
BWD_GAP = re.compile(r"^[\s,:;.\-–—(\[|]*(?:\(?\d{4}\)?[\s,;:]*)?(?:status:?\s*)?$", re.I)
FOLLOW = re.compile(r"research|papers|working|\bcv\b|cv[._-]|vita", re.I)
BOLD_OPEN, BOLD_CLOSE = "\x02", "\x03"

_host_last = defaultdict(float)
_host_lock = defaultdict(threading.Lock)
_robots, _robots_lock = {}, threading.Lock()
_log, _log_lock = [], threading.Lock()


def polite_get(url):
    host = urlparse(url).netloc
    with _host_lock[host]:
        wait = 1.0 - (time.time() - _host_last[host])
        if wait > 0:
            time.sleep(wait)
        try:
            return requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
        finally:
            _host_last[host] = time.time()


def allowed(url):
    p = urlparse(url)
    base = "%s://%s" % (p.scheme, p.netloc)
    with _robots_lock:
        rp = _robots.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = polite_get(base + "/robots.txt")
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            elif r.status_code in (401, 403):
                rp.disallow_all = True
            else:
                rp.allow_all = True
        except Exception:
            rp.allow_all = True
        with _robots_lock:
            _robots[base] = rp
    return rp.can_fetch(UA, url)


class TextLinks(HTMLParser):
    BLOCK = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "section",
             "article", "dd", "dt", "blockquote", "hr", "td"}
    EMPH = {"b", "strong", "em", "i", "a"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.links, self.skip, self._a = [], [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in self.EMPH:
            self.out.append(BOLD_OPEN)
        if tag == "a":
            self._a = [dict(attrs).get("href") or "", []]

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag in self.EMPH:
            self.out.append(BOLD_CLOSE)
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and self._a:
            self.links.append((self._a[0], " ".join(self._a[1]).strip()))
            self._a = None

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(data)
        if self._a is not None:
            self._a[1].append(data)


def to_lines(text):
    lines = []
    for l in text.split("\n"):
        l = re.sub(r"[ \t\r\f\v\xa0]+", " ", l).strip()
        if l.replace(BOLD_OPEN, "").replace(BOLD_CLOSE, "").strip():
            lines.append(l)
    return lines


def clean(s):
    return re.sub(r"\s+", " ", s.replace(BOLD_OPEN, "").replace(BOLD_CLOSE, "")).strip()


def fetch_doc(url, author_id):
    rec = dict(author_id=author_id, url=url, status="", kind="", chars=0)
    try:
        if not allowed(url):
            rec["status"] = "robots-disallow"; return rec, None, []
        r = polite_get(url)
        rec["status"] = "http%d" % r.status_code
        if r.status_code != 200:
            return rec, None, []
        ctype = r.headers.get("Content-Type", "").lower()
        final = r.url
        if "pdf" in ctype or final.lower().endswith(".pdf"):
            rec["kind"] = "pdf"
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
                tf.write(r.content); tf.flush()
                out = subprocess.run(["pdftotext", "-q", tf.name, "-"], capture_output=True, timeout=60)
            txt = out.stdout.decode("utf-8", "ignore")
            # pdftotext breaks lines inside sentences; keep line structure (used for title fallback)
            lines = to_lines(txt)
            rec["chars"] = len(txt)
            return rec, lines, []
        if "html" not in ctype and "xml" not in ctype and ctype:
            rec["kind"] = ctype[:30]; return rec, None, []
        rec["kind"] = "html"
        p = TextLinks()
        p.feed(r.text)
        lines = to_lines("".join(p.out))
        rec["chars"] = sum(len(l) for l in lines)
        links = [(urldefrag(urljoin(final, h))[0], t) for h, t in p.links if h and not h.startswith(("mailto:", "javascript:"))]
        rec["final_url"] = final
        return rec, lines, links
    except Exception as e:
        rec["status"] = "err:%s" % type(e).__name__
        return rec, None, []


TITLE_JUNK = re.compile(r"^(with|joint with|pdf|ssrn|link|download|abstract|slides|paper|online appendix|appendix|"
                        r"working papers?|research|publications|cv|draft)\b", re.I)


def extract_title(lines, li, start_in_line):
    """Return (title, confidence). Only text that appears on the page is returned."""
    line = lines[li]
    before = line[:start_in_line]
    # 1) quoted text before the phrase on the same line
    cb = clean(before)
    starts_own = len(cb.split()) < 4 or re.match(r"^\(?(joint )?with\b", cb, re.I)
    # quoted title; may span up to 3 earlier lines (PDF line wrapping) when this line starts with the phrase or "(with ..."
    ctx = clean(" ".join(([lines[j] for j in range(max(0, li - 3), li)] if starts_own else []) + [before]))
    q = re.findall(r"[\"“]([^\"”]{15,250})[\"”]", ctx)
    if q:
        return q[-1].strip(" ,.;:"), "high"
    # 2) emphasised (b/strong/em/i/a) segment on same line before phrase, or on up to 3 preceding lines
    # look at preceding lines only when the phrase starts its own line (otherwise the title is on this line,
    # and a quote on an earlier line belongs to a different paper)
    segs = [before] + ([lines[j] for j in range(li - 1, max(-1, li - 4), -1)] if starts_own else [])
    for k, seg in enumerate(segs):
        em = re.findall(BOLD_OPEN + "([^" + BOLD_OPEN + BOLD_CLOSE + "]{15,250})" + BOLD_CLOSE, seg)
        em = [clean(e) for e in em]
        em = [e for e in em if not JANY.search(e) or len(e) > 60]
        em = [e for e in em if not STATUS.search(e) and not TITLE_JUNK.match(e) and len(e.split()) >= 3]
        if em:
            q2 = re.findall(r"[\"“]([^\"”]{15,250})[\"”]", clean(seg)) if k else []
            return (q2[-1] if q2 else em[-1]).strip(" .,;:"), "high"
        if k:
            q2 = re.findall(r"[\"“]([^\"”]{15,250})[\"”]", clean(seg))
            if q2:
                return q2[-1].strip(), "high"
    # 3) fallback: "Title (with coauthors) ..." on the same line -> text before "(with"
    mw = re.match(r"^(.{15,250}?)\s*\(\s*(?:joint\s+)?with\b", cb, re.I)
    if mw:
        return mw.group(1).strip(" ,;:"), "low"
    # 4) fallback: text before the phrase on the same line, else nearest preceding line
    b = cb.strip(" ,;:([-–—")
    if len(b.split()) >= 4 and not re.match(r"^\(?(joint )?with\b", cb, re.I):
        return b[-250:], "low"
    for j in range(li - 1, max(-1, li - 3), -1):
        c = clean(lines[j])
        if 15 <= len(c) <= 250 and not STATUS.search(c):
            return c, "low"
    return "", "low"


CTX_REFEREE = re.compile(r"referee|reviewer|ad hoc|editorial board|associate editor|reviewing for|review(ed)? for", re.I)
CTX_PUBLISHED = re.compile(r"forthcoming|published|accepted|conditionally accepted|in press|\b(19|20)\d\d,\s*\d+\s*\(|vol\.|pp\.", re.I)


def find_candidates(lines, author, url, page_kind):
    out = []
    for li, line in enumerate(lines):
        plain = clean(line)
        for m in STATUS.finditer(line):
            # journal within ~200 chars of the phrase (previous, current and next line joined)
            prev = clean(lines[li - 1]) if li > 0 else ""
            nxt = clean(lines[li + 1]) if li + 1 < len(lines) else ""
            head = (prev + " ") if prev else ""
            joined = head + plain + ((" " + nxt) if nxt else "")
            approx = len(head) + len(clean(line[:m.start()]))
            sm = STATUS.search(joined, max(0, approx - 3))
            if not sm:
                continue
            off = sm.start()
            # The journal must be syntactically attached to the phrase, e.g. "R&R at The Accounting Review",
            # "Revise and resubmit, Contemporary Accounting Research", "Management Science, R&R",
            # "[Revise & Resubmit, Management Science]". Merely being within 200 chars is not enough:
            # in the first prototype run that rule assigned "R&R at Journal of Financial Economics" to an
            # adjacent "Accepted at Management Science".
            best = None
            for code, jre in JRE:
                for jm in jre.finditer(joined):
                    if jm.start() >= sm.end():
                        gap, d = joined[sm.end():jm.start()], jm.start() - sm.end()
                        ok = d <= 200 and FWD_GAP.match(gap)
                    elif jm.end() <= off:
                        gap, d = joined[jm.end():off], off - jm.end()
                        ok = d <= 200 and BWD_GAP.match(gap)
                    else:
                        ok = False
                    if ok and (best is None or d < best[0]):
                        best = (d, code, jm.group(0))
            if not best:
                continue
            s0 = max(0, min(off - 120, len(joined) - 300))
            snippet = joined[s0:s0 + 300]
            assert sm.group(0) in snippet
            title, conf = extract_title(lines, li, m.start())
            near = joined[max(0, off - 250): off + 250]
            out.append(dict(
                title=title or "unknown", title_confidence=conf, journal=best[1], journal_match_text=best[2],
                journal_distance_chars=best[0], status_phrase=m.group(0), author_name=author["display_name"],
                openalex_id=author["author_id"], source_url=url, page_kind=page_kind, snippet=snippet,
                flag_referee_context=bool(CTX_REFEREE.search(near)),
                flag_published_context=bool(CTX_PUBLISHED.search(clean(line))),
                checked_date=TODAY))
    return out


def scan_author(author, urls):
    cands, visited, budget = [], set(), 2
    for u in urls:
        rec, lines, links = fetch_doc(u, author["author_id"])
        with _log_lock:
            _log.append(rec)
        visited.add(u)
        if lines is None:
            continue
        cands += find_candidates(lines, author, rec.get("final_url", u), rec["kind"])
        host = urlparse(rec.get("final_url", u)).netloc
        follow = []
        for h, t in links:
            if urlparse(h).netloc != host or h in visited or h in follow:
                continue
            path = urlparse(h).path.lower()
            if path.endswith(".pdf"):
                if re.search(r"(^|[/_.-])(cv|vita|curriculum)", path):
                    follow.append(h)
            elif FOLLOW.search(t or "") or FOLLOW.search(path):
                follow.append(h)
        for h in follow[:budget]:
            budget -= 1
            rec2, lines2, _ = fetch_doc(h, author["author_id"])
            with _log_lock:
                _log.append(rec2)
            visited.add(h)
            if lines2:
                cands += find_candidates(lines2, author, rec2.get("final_url", h), rec2["kind"])
        if budget <= 0:
            break
    # de-duplicate within author on (source_url, snippet)
    seen, uniq = set(), []
    for c in cands:
        k = (c["source_url"], c["snippet"])
        if k not in seen:
            seen.add(k); uniq.append(c)
    return uniq


def main():
    t0 = time.time()
    authors = {a["author_id"]: a for a in csv.DictReader(open(os.path.join(DATA, "cohort_authors.csv")))}
    urls = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(DATA, "homepages_orcid.csv"))):
        if r["name_match"] != "no":
            urls[r["author_id"]].append(r["url"])
    p = os.path.join(DATA, "homepages_institutional.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p)):
            # keep profile/directory pages only (drops news stories that merely mention the person)
            if r["title_has_name"] == "1" and re.search(r"/(people|profile|faculty|directory|experts?)/", r["url"], re.I):
                urls[r["author_id"]].append(r["url"])
    # step 2c: curated faculty-directory route (personal site / CV first, then the profile page itself)
    p = os.path.join(DATA, "homepages_directory.csv")
    if os.path.exists(p):
        rank = {"personal": 0, "cv": 1, "profile": 2}
        for r in sorted(csv.DictReader(open(p)), key=lambda r: rank.get(r["url_kind"], 3)):
            urls[r["author_id"]].append(r["url"])
    elig = {}
    for aid, us in urls.items():
        a = authors.get(aid)
        if not a or a["acc5_flag"] != "1":
            continue
        good = []
        for u in us:
            u = u.strip()
            if not u.startswith("http"):
                u = "http://" + u
            if not SKIP_HOSTS.search(urlparse(u).netloc + urlparse(u).path) and u not in good:
                good.append(u)
        if good:
            elig[aid] = good[:4]
    ids = sorted(elig)
    random.Random(SEED).shuffle(ids)
    ids = ids[:MAX_AUTHORS] if MAX_AUTHORS else ids
    print("accounting-5 authors with >=1 crawlable URL: %d; scanning %d" % (len(elig), len(ids)), flush=True)
    allc = []
    with ThreadPoolExecutor(10) as ex:
        for k, c in enumerate(ex.map(lambda i: scan_author(authors[i], elig[i]), ids)):
            allc += c
            if (k + 1) % 25 == 0:
                print("  %d authors done, %d candidates, %.0fs" % (k + 1, len(allc), time.time() - t0), flush=True)
    # staleness check: does the extracted title already appear as a published 2021-2026 article in the six
    # journals (OpenAlex, data/cohort_works.csv)? Exact-ish fuzzy match only (difflib ratio >= 0.85).
    import difflib
    nz = lambda t: re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()
    pub = {}
    for r in csv.DictReader(open(os.path.join(DATA, "cohort_works.csv"))):
        pub.setdefault(nz(r["title"]), (r["journal"], r["publication_year"], r["doi"]))
    keys = list(pub)
    for i, c in enumerate(allc):
        c["candidate_id"] = i + 1
        m = difflib.get_close_matches(nz(c["title"]), keys, n=1, cutoff=0.85) if len(nz(c["title"])) >= 20 else []
        c["already_published_match"] = ("%s %s %s" % pub[m[0]]) if m else ""
    json.dump(allc, open(os.path.join(DATA, "rr_candidates.json"), "w"), indent=1, ensure_ascii=False)
    with open(os.path.join(DATA, "scan_fetch_log.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["author_id", "url", "final_url", "status", "kind", "chars"], extrasaction="ignore")
        w.writeheader(); w.writerows(_log)
    st = defaultdict(int)
    for r in _log:
        st[r["status"]] += 1
    print("fetches %d; status %s" % (len(_log), dict(st)))
    print("authors scanned %d; authors with >=1 candidate %d; candidates %d (high-confidence titles %d)"
          % (len(ids), len({c["openalex_id"] for c in allc}), len(allc), sum(c["title_confidence"] == "high" for c in allc)))
    print("by journal:", {j: sum(c["journal"] == j for c in allc) for j, _ in JOURNALS})
    print("flags: referee_context %d, published_context %d" % (sum(c["flag_referee_context"] for c in allc),
                                                               sum(c["flag_published_context"] for c in allc)))
    print("already-published title matches: %d" % sum(bool(c["already_published_match"]) for c in allc))
    print("runtime %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
