#!/usr/bin/env python3
"""Step 1b: add top-5 accounting articles that the OpenAlex source query missed.

The author keeps journal-by-year DOI lists for TAR, JAR, JAE, CAR and RAST in
~/Library/CloudStorage/Box-Box/Data/meta_analysis/DOIs/<J>_DOIs_By_Year/<J>_<year>.csv (built from the
publishers' tables of contents, filed by print year). OpenAlex dates articles by first online publication, so
papers printed in 2021 but online in 2020 fall outside step 1's window; a few others are filed under another
source id. This step looks up every 2021-2026 DOI from those lists that is not yet in cohort_works.csv
(OpenAlex /works?filter=doi:..., 40 DOIs per request) and appends the works and any new authors.
Existing authors who gain an accounting-5 article have their counts and acc5_flag updated.
"""
import csv, glob, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
c1 = importlib.import_module("01_cohort")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SRC = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/Library/CloudStorage/Box-Box/Data/meta_analysis/DOIs")
ACC5 = ["JAE", "JAR", "TAR", "CAR", "RAST"]


def main():
    works = list(csv.DictReader(open(os.path.join(DATA, "cohort_works.csv"))))
    have = {(w["doi"] or "").lower().replace("https://doi.org/", "") for w in works}
    local = {}
    for j in ACC5:
        for p in sorted(glob.glob(os.path.join(SRC, "%s_DOIs_By_Year" % j, "%s_20*.csv" % j))):
            y = int(os.path.basename(p)[-8:-4])
            if not 2021 <= y <= 2026:
                continue
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                d = (r.get("DOI") or "").strip().lower()
                if d and d not in have:
                    local[d] = j
    print("local DOI lists 2021-2026: %d DOIs not in the OpenAlex cohort" % len(local))
    new_rows, found = [], set()
    # one DOI per request: singleton lookups (/works/doi:...) still answer when the daily list-query budget is spent
    import urllib.parse
    results = []
    for k, doi in enumerate(sorted(local)):
        try:
            results.append(c1.get("/works/doi:" + urllib.parse.quote(doi, safe="/"),
                                  {"select": "id,doi,title,publication_year,publication_date,authorships,type"}))
        except RuntimeError as e:
            print("  not found", doi, str(e)[:80])
        if k % 100 == 0:
            print("  looked up", k, "/", len(local), flush=True)
    for wk in results:
        if True:
            doi = (wk.get("doi") or "").lower().replace("https://doi.org/", "")
            if doi not in local:
                continue
            found.add(doi)
            for a in wk.get("authorships") or []:
                au = a.get("author") or {}
                if not au.get("id"):
                    continue
                new_rows.append(dict(
                    work_id=c1.short(wk["id"]), doi=wk.get("doi") or "", journal=local[doi],
                    publication_year=wk.get("publication_year"), publication_date=wk.get("publication_date") or "",
                    title=(wk.get("title") or "").replace("\n", " "), author_id=c1.short(au["id"]),
                    author_name=au.get("display_name") or "", orcid=(au.get("orcid") or "").replace("https://orcid.org/", ""),
                    raw_author_name=a.get("raw_author_name") or "",
                    institution_ids="|".join(c1.short(x.get("id")) for x in a.get("institutions") or [] if x.get("id")),
                    institution_names="|".join(x.get("display_name") or "" for x in a.get("institutions") or [])))
    print("found in OpenAlex: %d of %d DOIs; %d authorship rows" % (len(found), len(local), len(new_rows)))
    with open(os.path.join(DATA, "cohort_works.csv"), "a", newline="") as f:
        csv.DictWriter(f, fieldnames=list(works[0].keys())).writerows(new_rows)

    authors = list(csv.DictReader(open(os.path.join(DATA, "cohort_authors.csv"))))
    byid = {a["author_id"]: a for a in authors}
    cols = list(authors[0].keys())
    add = defaultdict(lambda: defaultdict(int))
    meta = {}
    for r in {(r["author_id"], r["work_id"]): r for r in new_rows}.values():
        add[r["author_id"]][r["journal"]] += 1
        m = meta.setdefault(r["author_id"], dict(name=r["author_name"], orcid=r["orcid"], date="", ids="", names="", year=0))
        m["year"] = max(m["year"], r["publication_year"] or 0)
        if r["institution_ids"] and r["publication_date"] >= m["date"]:
            m.update(date=r["publication_date"], ids=r["institution_ids"], names=r["institution_names"])
    upgraded = 0
    fresh = [a for a in add if a not in byid]
    lki = {}
    for aid in fresh:
        try:
            au = c1.get("/authors/" + aid, {"select": "id,orcid,last_known_institutions,works_count"})
            lki[aid] = au
        except RuntimeError:
            pass
    for aid, cnt in add.items():
        if aid in byid:
            a = byid[aid]
            was = a["acc5_flag"]
            for j, n in cnt.items():
                a["n_" + j] = int(a["n_" + j]) + n
            a["n_acc5"] = sum(int(a["n_" + j]) for j in ACC5)
            a["n_total"] = int(a["n_total"]) + sum(cnt.values())
            a["acc5_flag"] = int(a["n_acc5"] > 0)
            upgraded += str(was) == "0" and a["acc5_flag"] == 1
        else:
            m, au = meta[aid], lki.get(aid, {})
            k = au.get("last_known_institutions") or []
            row = {c: "" for c in cols}
            row.update(author_id=aid, display_name=m["name"],
                       orcid=m["orcid"] or (au.get("orcid") or "").replace("https://orcid.org/", ""),
                       last_known_institution_ids="|".join(c1.short(x.get("id")) for x in k if x.get("id")),
                       last_known_institutions="|".join(x.get("display_name") or "" for x in k),
                       latest_paper_institution_ids=m["ids"], latest_paper_institutions=m["names"],
                       latest_year=m["year"], oa_works_count=au.get("works_count", ""))
            for j in ["JAE", "JAR", "TAR", "CAR", "RAST", "MS"]:
                row["n_" + j] = cnt.get(j, 0)
            row["n_acc5"] = sum(cnt.get(j, 0) for j in ACC5)
            row["n_total"] = sum(cnt.values())
            row["acc5_flag"] = int(row["n_acc5"] > 0)
            authors.append(row)
    with open(os.path.join(DATA, "cohort_authors.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(authors)
    print("new authors added: %d; existing Management-Science-only authors now accounting-5: %d" % (len(fresh), upgraded))
    print("accounting-5 author ids now: %d" % sum(str(a["acc5_flag"]) == "1" for a in authors))
    print("OpenAlex requests: %d" % c1.NREQ)


if __name__ == "__main__":
    main()
