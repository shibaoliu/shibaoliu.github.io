#!/usr/bin/env python3
"""Step 1: build the author cohort from OpenAlex.

Six journals, publication_year 2021-2026, type=article.
Outputs:
  data/journal_sources.csv   resolved OpenAlex source ids (verified by ISSN + display_name)
  data/cohort_works.csv      one row per (work, authorship)
  data/cohort_authors.csv    one row per OpenAlex author id
  data/institutions.csv      OpenAlex institution id -> display name, homepage_url (for step 2b)
"""
import csv, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
MAILTO = "tanglin817@gmail.com"
API = "https://api.openalex.org"

JOURNALS = [  # (short code, ISSN used for lookup, expected display_name)
    ("JAE", "0165-4101", "Journal of Accounting and Economics"),
    ("JAR", "0021-8456", "Journal of Accounting Research"),
    ("TAR", "0001-4826", "The Accounting Review"),
    ("CAR", "0823-9150", "Contemporary Accounting Research"),
    ("RAST", "1380-6653", "Review of Accounting Studies"),
    ("MS", "0025-1909", "Management Science"),
]
ACC5 = {"JAE", "JAR", "TAR", "CAR", "RAST"}
NREQ = 0
# Without a key OpenAlex (2026) allows ~1000 requests/day per IP and refuses cursor paging past page 1,
# so we use page= paging (fine: every journal has < 10,000 works in the window). Set OPENALEX_API_KEY to use cursors.
API_KEY = os.environ.get("OPENALEX_API_KEY", "")


def get(path, params):
    global NREQ
    params = dict(params, mailto=MAILTO)
    if API_KEY:
        params["api_key"] = API_KEY
    url = API + path + "?" + urllib.parse.urlencode(params, safe=":|,")
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "shibaoliu.github.io RR tracker (contact: %s)" % MAILTO})
            with urllib.request.urlopen(req, timeout=60) as r:
                NREQ += 1
                time.sleep(0.15)  # polite: < 10 req/s
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError("OpenAlex 404: " + url)
            if e.code in (401, 403):
                raise RuntimeError("OpenAlex refused (%s): %s" % (e.code, e.read()[:300]))
            print("  retry", attempt, e, file=sys.stderr)
            time.sleep(2 ** attempt)
        except Exception as e:  # retry with backoff
            print("  retry", attempt, e, file=sys.stderr)
            time.sleep(2 ** attempt)
    raise RuntimeError("failed: " + url)


def short(oid):
    return oid.rsplit("/", 1)[-1] if oid else ""


def main():
    t0 = time.time()
    os.makedirs(DATA, exist_ok=True)
    # 1. resolve source ids
    sources = []
    for code, issn, name in JOURNALS:
        res = get("/sources", {"filter": "issn:" + issn})["results"]
        match = [s for s in res if s["display_name"].lower() == name.lower()]
        assert len(match) == 1, (code, issn, [s["display_name"] for s in res])
        s = match[0]
        sources.append(dict(code=code, issn=issn, source_id=short(s["id"]), display_name=s["display_name"],
                            issns="|".join(s.get("issn") or [])))
        print(code, short(s["id"]), s["display_name"])
    with open(os.path.join(DATA, "journal_sources.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sources[0].keys()))
        w.writeheader(); w.writerows(sources)

    # 2. works, cursor paging
    work_rows = []
    per_journal = {}
    for s in sources:
        cursor, n, page = "*", 0, 1
        while cursor:
            q = {"filter": "primary_location.source.id:%s,publication_year:2021-2026,type:article" % s["source_id"],
                 "per-page": 200, "sort": "publication_date:desc",
                 "select": "id,doi,title,publication_year,publication_date,authorships"}
            if API_KEY:
                q["cursor"] = cursor
            else:
                q["page"] = page
            d = get("/works", q)
            for wk in d["results"]:
                n += 1
                for a in wk.get("authorships") or []:
                    au = a.get("author") or {}
                    if not au.get("id"):
                        continue
                    work_rows.append(dict(
                        work_id=short(wk["id"]), doi=wk.get("doi") or "", journal=s["code"],
                        publication_year=wk.get("publication_year"), publication_date=wk.get("publication_date") or "",
                        title=(wk.get("title") or "").replace("\n", " "),
                        author_id=short(au["id"]), author_name=au.get("display_name") or "",
                        orcid=(au.get("orcid") or "").replace("https://orcid.org/", ""),
                        raw_author_name=a.get("raw_author_name") or "",
                        institution_ids="|".join(short(i.get("id")) for i in a.get("institutions") or [] if i.get("id")),
                        institution_names="|".join(i.get("display_name") or "" for i in a.get("institutions") or []),
                    ))
            page += 1
            cursor = d["meta"].get("next_cursor") if API_KEY else (None if n >= d["meta"]["count"] else "page")
            if not d["results"]:
                break
        per_journal[s["code"]] = n
        print("  %s works: %d (meta count %s)" % (s["code"], n, d["meta"]["count"]))
    with open(os.path.join(DATA, "cohort_works.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(work_rows[0].keys()))
        w.writeheader(); w.writerows(work_rows)

    # 3. authors table
    A = {}
    seen = set()
    for r in work_rows:
        key = (r["author_id"], r["work_id"])
        if key in seen:
            continue
        seen.add(key)
        a = A.setdefault(r["author_id"], dict(author_id=r["author_id"], display_name=r["author_name"], orcid=r["orcid"],
                                              counts=defaultdict(int), latest_year=0, latest_inst_ids="", latest_inst_names="",
                                              _latest_date=""))
        a["counts"][r["journal"]] += 1
        if r["orcid"] and not a["orcid"]:
            a["orcid"] = r["orcid"]
        y = r["publication_year"] or 0
        a["latest_year"] = max(a["latest_year"], y)
        if r["institution_ids"] and r["publication_date"] >= a["_latest_date"]:
            a["_latest_date"] = r["publication_date"]
            a["latest_inst_ids"], a["latest_inst_names"] = r["institution_ids"], r["institution_names"]

    # 3b. OpenAlex author records -> last_known_institutions (batched 50 ids/request)
    ids = sorted(A)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        d = get("/authors", {"filter": "openalex_id:" + "|".join(chunk), "per-page": 50,
                             "select": "id,display_name,orcid,last_known_institutions,works_count"})
        for au in d["results"]:
            a = A.get(short(au["id"]))
            if a is None:
                continue
            lki = au.get("last_known_institutions") or []
            a["lki_ids"] = "|".join(short(x.get("id")) for x in lki if x.get("id"))
            a["lki_names"] = "|".join(x.get("display_name") or "" for x in lki)
            if au.get("orcid") and not a["orcid"]:
                a["orcid"] = au["orcid"].replace("https://orcid.org/", "")
            a["oa_works_count"] = au.get("works_count")
        if i % 1000 == 0:
            print("  authors fetched", i + len(chunk), "/", len(ids))

    codes = [c for c, _, _ in JOURNALS]
    out = []
    for a in A.values():
        row = dict(author_id=a["author_id"], display_name=a["display_name"], orcid=a["orcid"],
                   last_known_institution_ids=a.get("lki_ids", ""), last_known_institutions=a.get("lki_names", ""),
                   latest_paper_institution_ids=a["latest_inst_ids"], latest_paper_institutions=a["latest_inst_names"])
        for c in codes:
            row["n_" + c] = a["counts"].get(c, 0)
        row["n_acc5"] = sum(a["counts"].get(c, 0) for c in ACC5)
        row["n_total"] = sum(a["counts"].values())
        row["acc5_flag"] = int(row["n_acc5"] > 0)
        row["latest_year"] = a["latest_year"]
        row["oa_works_count"] = a.get("oa_works_count", "")
        out.append(row)
    out.sort(key=lambda r: (-r["acc5_flag"], r["display_name"]))
    with open(os.path.join(DATA, "cohort_authors.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)

    # 4. institutions (homepage_url) for accounting-5 authors' institutions
    inst_ids = set()
    for r in out:
        if r["acc5_flag"]:
            for x in (r["last_known_institution_ids"] or r["latest_paper_institution_ids"]).split("|"):
                if x:
                    inst_ids.add(x)
    inst_ids = sorted(inst_ids)
    insts = []
    for i in range(0, len(inst_ids), 50):
        d = get("/institutions", {"filter": "openalex_id:" + "|".join(inst_ids[i:i + 50]), "per-page": 50,
                                  "select": "id,display_name,homepage_url,country_code,type"})
        for it in d["results"]:
            insts.append(dict(institution_id=short(it["id"]), display_name=it["display_name"],
                              homepage_url=it.get("homepage_url") or "", country_code=it.get("country_code") or "",
                              type=it.get("type") or ""))
    with open(os.path.join(DATA, "institutions.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["institution_id", "display_name", "homepage_url", "country_code", "type"])
        w.writeheader(); w.writerows(insts)

    # summary
    print("\nworks per journal:", per_journal)
    for c in codes:
        print("  authors with >=1 %s paper: %d" % (c, sum(1 for r in out if r["n_" + c] > 0)))
    print("total unique authors (6 journals):", len(out))
    print("accounting-5 cohort (>=1 paper in JAE/JAR/TAR/CAR/RAST):", sum(r["acc5_flag"] for r in out))
    print("MS-only authors:", sum(1 for r in out if not r["acc5_flag"]))
    print("authors with ORCID: all=%d acc5=%d" % (sum(1 for r in out if r["orcid"]), sum(1 for r in out if r["orcid"] and r["acc5_flag"])))
    print("institutions resolved:", len(insts), "with homepage_url:", sum(1 for x in insts if x["homepage_url"]))
    print("OpenAlex requests: %d; runtime %.1fs" % (NREQ, time.time() - t0))


if __name__ == "__main__":
    main()
