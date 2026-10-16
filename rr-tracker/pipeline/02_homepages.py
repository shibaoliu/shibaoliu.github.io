#!/usr/bin/env python3
"""Step 2a: homepage discovery via the public ORCID API (no search engines).

For every cohort author with an ORCID: GET https://pub.orcid.org/v3.0/{orcid}/person
(the /person record embeds researcher-urls, so one request per ORCID).
Each distinct ORCID is queried once (OpenAlex sometimes splits one person into several author ids
that share an ORCID).

Outputs:
  data/orcid_person_cache.jsonl  raw-ish cache (orcid, http status, names, researcher-urls)
  data/homepages_orcid.csv       one row per (author_id, url): url, url_name, source, orcid_name, name_match
"""
import csv, json, os, sys, time, threading, unicodedata, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = "shibaoliu.github.io RR tracker (contact: tanglin817@gmail.com)"
CACHE = os.path.join(DATA, "orcid_person_cache.jsonl")
WORKERS = 6           # ORCID public API documented limit: 24 req/s; we stay far below
MIN_INTERVAL = 0.6    # per worker -> ~10 req/s aggregate max

lock = threading.Lock()


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return "".join(c if c.isalpha() else " " for c in s).split()


def fetch(orcid):
    url = "https://pub.orcid.org/v3.0/%s/person" % orcid
    t = time.time()
    rec = {"orcid": orcid, "status": None, "given": "", "family": "", "credit": "", "urls": []}
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            rec["status"] = 200
            nm = d.get("name") or {}
            rec["given"] = ((nm.get("given-names") or {}).get("value")) or ""
            rec["family"] = ((nm.get("family-name") or {}).get("value")) or ""
            rec["credit"] = ((nm.get("credit-name") or {}).get("value")) or ""
            for u in ((d.get("researcher-urls") or {}).get("researcher-url")) or []:
                rec["urls"].append({"url": ((u.get("url") or {}).get("value")) or "",
                                    "url_name": u.get("url-name") or ""})
            break
        except urllib.error.HTTPError as e:
            rec["status"] = e.code
            if e.code in (404, 409, 410):
                break
            time.sleep(2 ** attempt)
        except Exception as e:
            rec["status"] = "err:%s" % type(e).__name__
            time.sleep(2 ** attempt)
    dt = time.time() - t
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    return rec


def main():
    t0 = time.time()
    authors = list(csv.DictReader(open(os.path.join(DATA, "cohort_authors.csv"))))
    orcids = sorted({a["orcid"] for a in authors if a["orcid"]})
    done = {}
    if os.path.exists(CACHE):
        for line in open(CACHE):
            r = json.loads(line)
            if r.get("status") == 200 or r.get("status") in (404, 409, 410):
                done[r["orcid"]] = r
    todo = [o for o in orcids if o not in done]
    print("authors %d, distinct ORCIDs %d, cached %d, to fetch %d" % (len(authors), len(orcids), len(done), len(todo)))
    n = 0
    with open(CACHE, "a") as cf, ThreadPoolExecutor(WORKERS) as ex:
        for rec in ex.map(fetch, todo):
            done[rec["orcid"]] = rec
            with lock:
                cf.write(json.dumps(rec) + "\n")
            n += 1
            if n % 500 == 0:
                print("  fetched %d/%d  %.0fs" % (n, len(todo), time.time() - t0), flush=True)

    rows = []
    for a in authors:
        r = done.get(a["orcid"]) if a["orcid"] else None
        if not r:
            continue
        on = norm(" ".join([r["given"], r["family"]]))
        an = norm(a["display_name"])
        # name check: ORCID family name must appear in OpenAlex display name (guards against wrong ORCID links)
        fam = norm(r["family"])
        name_match = "yes" if fam and all(t in an for t in fam) else ("unknown" if not fam else "no")
        for u in r["urls"]:
            if not u["url"]:
                continue
            rows.append(dict(author_id=a["author_id"], display_name=a["display_name"], orcid=a["orcid"],
                             acc5_flag=a["acc5_flag"], url=u["url"].strip(), url_name=u["url_name"],
                             source="orcid:researcher-urls", orcid_name=" ".join(on), name_match=name_match))
    with open(os.path.join(DATA, "homepages_orcid.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["author_id", "display_name", "orcid", "acc5_flag", "url", "url_name",
                                          "source", "orcid_name", "name_match"])
        w.writeheader(); w.writerows(rows)

    st = {}
    for r in done.values():
        st[str(r["status"])] = st.get(str(r["status"]), 0) + 1
    print("ORCID status counts:", st)
    have = {r["author_id"] for r in rows}
    for lab, sub in [("full cohort", authors), ("accounting-5", [a for a in authors if a["acc5_flag"] == "1"]),
                     ("MS-only", [a for a in authors if a["acc5_flag"] == "0"])]:
        k = sum(1 for a in sub if a["author_id"] in have)
        ko = sum(1 for a in sub if a["orcid"])
        print("%-13s authors %5d | with ORCID %5d (%.1f%%) | >=1 ORCID URL %5d (%.1f%% of all, %.1f%% of ORCID holders)"
              % (lab, len(sub), ko, 100 * ko / len(sub), k, 100 * k / len(sub), 100 * k / max(ko, 1)))
    print("URL rows %d; name_match counts %s" % (len(rows), {v: sum(1 for r in rows if r["name_match"] == v) for v in ("yes", "no", "unknown")}))
    print("runtime %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
