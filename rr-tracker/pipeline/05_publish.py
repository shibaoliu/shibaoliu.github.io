#!/usr/bin/env python3
"""Step 5: build the public tracker data (data/rr_public.json) from reviewed candidates.

Only candidates with verdict "publish" in data/rr_review.json reach the site. The review is done by an
independent checker against the live page (snippet present, R&R at the named journal, current, title as
written on the page). Entries are grouped by normalised title + journal, so coauthors who both list a paper
appear on one row, each with their own source link and check date.
Coverage is counted in people (OpenAlex author ids that share an ORCID are one person).
"""
import csv, difflib, json, os, re, unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def nz(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def tidy(name):
    # OpenAlex sometimes stores a name in capitals ("MIAO LIU")
    return name.title() if name.isupper() else name


def main():
    cands = {c["candidate_id"]: c for c in json.load(open(os.path.join(DATA, "rr_candidates.json")))}
    review = json.load(open(os.path.join(DATA, "rr_review.json")))
    authors = {a["author_id"]: a for a in csv.DictReader(open(os.path.join(DATA, "cohort_authors.csv")))}
    person = lambda aid: authors[aid]["orcid"] or aid

    rows = defaultdict(lambda: {"authors": []})
    for r in review:
        if r["verdict"] != "publish":
            continue
        c = cands[r["candidate_id"]]
        title = r.get("title") or c["title"]
        k = (nz(title), c["journal"])
        # coauthors' pages sometimes word the same title slightly differently: merge near-identical titles
        for k2 in rows:
            if k2[1] == k[1] and difflib.SequenceMatcher(None, k2[0], k[0]).ratio() >= 0.85:
                k = k2; break
        rows[k].update(title=title, journal=c["journal"])
        if person(c["openalex_id"]) not in {person(a["openalex_id"]) for a in rows[k]["authors"]}:
            rows[k]["authors"].append(dict(name=tidy(r.get("author_name") or c["author_name"]), openalex_id=c["openalex_id"], source_url=c["source_url"],
                                           snippet=c["snippet"], checked_date=r.get("checked_date") or c["checked_date"]))

    acc5 = [a for a in authors.values() if a["acc5_flag"] == "1"]
    people_total = {person(a["author_id"]) for a in acc5}
    reached = set()
    for f in csv.DictReader(open(os.path.join(DATA, "scan_fetch_log.csv"))):
        if f["status"] == "http200" and f["author_id"] in authors and authors[f["author_id"]]["acc5_flag"] == "1":
            reached.add(person(f["author_id"]))
    st = json.load(open(os.path.join(DATA, "run_stats.json")))
    out = dict(
        generated=st["run_date"],
        coverage=dict(authors_total=len(people_total), authors_reached=len(reached)),
        method=[
            "Authors: everyone with at least one article in JAE, JAR, TAR, CAR or RAST published %s (OpenAlex), "
            "%s people." % (st["window"], format(len(people_total), ",")),
            "Pages: the personal website listed on the author's ORCID record, and the faculty profile (plus any personal "
            "site or CV it links to) found through a curated list of %d accounting faculty directories. "
            "%s of %s authors had at least one page that could be read (%.1f%%); the rest list no site we could find, "
            "or their pages block automated reading." % (st["n_directories"], format(len(reached), ","),
                                                         format(len(people_total), ","), 100 * len(reached) / len(people_total)),
            "A paper is listed only when the page itself attaches a revise-and-resubmit phrase to one of the six journals "
            "(for example, “R&amp;R at The Accounting Review”). The exact wording is shown under each entry.",
            "Papers that Crossref or OpenAlex show as already published are removed, and every entry was checked "
            "against the live page before it was listed.",
            "Missing or out-of-date entry? Email <a href=\"mailto:lius@fit.edu\">lius@fit.edu</a> with the page that lists it.",
        ],
        entries=sorted(rows.values(), key=lambda x: (x["journal"], nz(x["title"]))),
    )
    json.dump(out, open(os.path.join(DATA, "rr_public.json"), "w"), indent=1, ensure_ascii=False)
    print("public entries %d; people reached %d of %d" % (len(out["entries"]), len(reached), len(people_total)))


if __name__ == "__main__":
    main()
