#!/usr/bin/env python3
"""Step 4b (weekly runs): carry earlier review verdicts forward; queue only what is new for review.

argv[1] = folder with the previous run's rr_candidates.json and rr_review.json (e.g. data/prev_20261016).
A new candidate inherits an earlier verdict (and the reviewer's exact title) when the same author's same page
shows the same wording: identical snippet, or identical machine-extracted title and journal on that page.
Inherited "publish" verdicts are dated today (re-confirmed on the live page); a Crossref/OpenAlex hit from
step 4 still overrides them. An earlier "publish" entry with no match this week is
  - dropped, if its page was read this week (HTTP 200) and no longer shows the R&R wording;
  - kept with its old check date, if its page could not be read this week (block, timeout).
Writes data/rr_review.json (one verdict per current candidate) and data/review_in_new.json (to review).
"""
import csv, datetime, json, os, re, sys, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PREV = sys.argv[1]
TODAY = datetime.date.today().isoformat()


def nz(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip()


def keys(c):
    return [("s", c["openalex_id"], c["source_url"], nz(c["snippet"])),
            ("t", c["openalex_id"], c["source_url"], c["journal"], nz(c["title"]))]


def main():
    cur = json.load(open(os.path.join(DATA, "rr_candidates.json")))
    old = {c["candidate_id"]: c for c in json.load(open(os.path.join(PREV, "rr_candidates.json")))}
    oldrev = {r["candidate_id"]: r for r in json.load(open(os.path.join(PREV, "rr_review.json")))}
    index = {}
    for cid, r in oldrev.items():
        for k in keys(old[cid]):
            index.setdefault(k, (cid, r))
    status = {}
    for f in csv.DictReader(open(os.path.join(DATA, "scan_fetch_log.csv"))):
        for u in (f["url"], f.get("final_url") or ""):
            if u:
                status[u] = f["status"] if status.get(u) != "http200" else "http200"
    review, todo, matched_old = [], [], set()
    for c in cur:
        hit = next((index[k] for k in keys(c) if k in index), None)
        stale = c.get("crossref_match") or c.get("already_published_match")
        if stale:
            review.append(dict(candidate_id=c["candidate_id"], verdict="drop", checked_date=TODAY,
                               reason="already published: " + (c.get("crossref_match") or c["already_published_match"])))
            if hit:
                matched_old.add(hit[0])
        elif hit:
            cid, r = hit
            matched_old.add(cid)
            rr = dict(r, candidate_id=c["candidate_id"], carried_from=cid)
            if r["verdict"] == "publish":
                rr["checked_date"] = TODAY
            review.append(rr)
        else:
            todo.append({k: c[k] for k in ("candidate_id", "author_name", "title", "journal", "status_phrase",
                                           "source_url", "snippet")})
    # earlier published entries that did not reappear this week
    nxt = max([c["candidate_id"] for c in cur] or [0])
    kept = dropped = 0
    for cid, r in oldrev.items():
        if r["verdict"] != "publish" or cid in matched_old:
            continue
        oc = old[cid]
        if status.get(oc["source_url"]) == "http200":
            dropped += 1
            print("dropped (page read, R&R wording gone): %s | %s" % (oc["author_name"], r.get("title") or oc["title"]))
            continue
        nxt += 1
        kept += 1
        cur.append(dict(oc, candidate_id=nxt))
        review.append(dict(r, candidate_id=nxt, carried_from=cid,
                           reason=r.get("reason", "") + " | page not readable %s (%s); kept from last check"
                           % (TODAY, status.get(oc["source_url"], "not fetched"))))
        print("kept, page unreadable this week: %s | %s" % (oc["author_name"], r.get("title") or oc["title"]))
    json.dump(cur, open(os.path.join(DATA, "rr_candidates.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(review, open(os.path.join(DATA, "rr_review.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(todo, open(os.path.join(DATA, "review_in_new.json"), "w"), indent=1, ensure_ascii=False)
    print("current candidates %d: inherited %d, new to review %d, stale %d; earlier entries kept (unreadable) %d, "
          "dropped (wording gone) %d" % (len(cur) - kept, sum(1 for r in review if r.get("carried_from")) - kept,
                                         len(todo), sum(1 for r in review if r["reason"].startswith("already published")),
                                         kept, dropped))


if __name__ == "__main__":
    main()
