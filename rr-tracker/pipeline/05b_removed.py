#!/usr/bin/env python3
"""Step 5b (weekly runs, after step 5): record R&R papers that left the public list, and why.

argv[1] = folder with the previous run's rr_public.json (e.g. data/prev_20261016), the same folder given to step 4b.
A paper "left the list" when it was in the previous rr_public.json and no current entry has the same journal and a
near-identical title (ratio >= 0.85, the step-5 grouping rule). Every such paper is kept in data/rr_removed.json,
across runs, with a status; the AcctRes page shows the four marked below:
  - pending (not shown): waiting for a reviewer. Carried to every later run until a verdict arrives;
  - published [shown]: Crossref has a journal article with the same title and author in the R&R journal itself
    (checked every run for every paper except not_removed; it overrides any verdict), or a reviewer says so;
  - accepted [shown]: a reviewer quotes the author's page or CV (accepted, conditionally accepted, forthcoming);
  - published_elsewhere [shown]: a reviewer confirms it appeared in a different journal (a Crossref hit outside the R&R
    journal, e.g. a proceedings abstract, is only a hint for the reviewer);
  - presumed_rejected [shown]: a reviewer read the author's page, found the R&R wording gone and no acceptance or
    publication. The verdict is accepted only if step 4b recorded this paper (same page, journal and title) as read
    with the wording gone in the run in which it left the list, and a Crossref search ran this run and found the
    paper in no journal (titles under 4 words cannot be searched, so they stay pending);
  - not_removed (not shown): a reviewer found it still listed as R&R (retitled, reworded or regrouped).
Reviewer verdicts are data/removed_review.json: [{title, journal, status, evidence, checked_date (YYYY-MM-DD)}].
Among valid verdicts dated on or after the run in which the paper left the list, the latest wins (on the same date,
the one later in the file); it overrides any earlier status, and an older exit's verdicts never apply to a new exit.
Invalid verdicts (missing field, unknown status or journal, impossible or future date) are ignored and listed in
removed_to_review.json, as are valid verdicts that match no paper. If Crossref fails, a paper keeps its previous status that run.
Papers still pending go to data/removed_to_review.json with what the reviewer needs.
"""
import datetime, difflib, importlib.util, json, os, re, sys, time, unicodedata
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PREV = sys.argv[1]
# the run date (set in data/run_stats.json for step 5), not the day this step happens to be run
TODAY = json.load(open(os.path.join(DATA, "run_stats.json")))["run_date"]
JOURNAL_NAME = {"JAE": "journal of accounting and economics", "JAR": "journal of accounting research",
                "TAR": "the accounting review", "CAR": "contemporary accounting research",
                "RAST": "review of accounting studies", "MS": "management science"}
VERDICTS = {"published", "accepted", "published_elsewhere", "presumed_rejected", "not_removed"}
SHOWN = {"published", "accepted", "published_elsewhere", "presumed_rejected"}
spec = importlib.util.spec_from_file_location("staleness", os.path.join(ROOT, "pipeline", "04_staleness.py"))
staleness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staleness)


def nz(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip()


def same(t1, j1, t2, j2):
    return j1 == j2 and difflib.SequenceMatcher(None, nz(t1), nz(t2)).ratio() >= 0.85


def load(name, default):
    p = os.path.join(DATA, name)
    return json.load(open(p)) if os.path.exists(p) else default


def crossref(x):
    """(in_rr_journal, other_hints, queried): journal articles with a near-identical title (>= 0.90) and one of the authors'
    family names, SSRN excluded (step 4's rules). Raises on a network error."""
    if len(nz(x["title"]).split()) < 4 or x["journal"] not in JOURNAL_NAME or not x["authors"]:
        return "", [], False  # step 4's short-title guard; nothing was checked
    want, other = nz(JOURNAL_NAME[x["journal"]]), []
    for a in x["authors"]:
        r = requests.get("https://api.crossref.org/works",
                         params={"query.bibliographic": x["title"], "rows": 8, "filter": "type:journal-article",
                                 "select": "DOI,title,author,container-title,issued", "mailto": "tanglin817@gmail.com"},
                         headers={"User-Agent": staleness.UA}, timeout=30)
        r.raise_for_status()
        fam = staleness.family(a["name"])
        for it in r.json()["message"]["items"]:
            venue = " ".join(it.get("container-title") or [])
            if it["DOI"].lower().startswith("10.2139/") or "ssrn" in venue.lower():
                continue
            t = (it.get("title") or [""])[0]
            if difflib.SequenceMatcher(None, staleness.nz(t), staleness.nz(x["title"])).ratio() < 0.90:
                continue
            fams = {staleness.nz(b.get("family", "")).split()[-1] for b in it.get("author", [])
                    if staleness.nz(b.get("family", ""))}
            if not fam or fam not in fams:
                continue
            y = ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0]
            desc = "%s (%s) doi:%s" % (venue or "no journal name", y, it["DOI"])
            if nz(venue) == want:
                return "Crossref: " + desc, [], True
            other.append(desc)
        time.sleep(0.2)
    return "", other, True


def valid(v):
    return (isinstance(v, dict) and v.get("status") in VERDICTS and v.get("journal") in JOURNAL_NAME
            and isinstance(v.get("title"), str) and isinstance(v.get("evidence"), str)
            and real_date(v.get("checked_date")))


def real_date(d):
    """A YYYY-MM-DD date that exists and is not in the future."""
    try:
        return re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) is not None and \
            datetime.date.fromisoformat(d) <= datetime.date.today()
    except (TypeError, ValueError):
        return False


def main():
    old = json.load(open(os.path.join(PREV, "rr_public.json")))["entries"]
    cur = json.load(open(os.path.join(DATA, "rr_public.json")))["entries"]
    try:
        verdicts = load("removed_review.json", [])
    except ValueError as err:
        sys.exit("data/removed_review.json is not valid JSON (%s); fix it and run 5b again" % err)
    if not isinstance(verdicts, list):
        sys.exit("data/removed_review.json must be a list of verdicts")
    cd = load("carryover_dropped.json", {})
    # guard against a forgotten run_date: it must not be older than this run's step 4b or the stored history
    for name, d in (("carryover_dropped.json", cd.get("date", "")),
                    ("rr_removed.json", load("rr_removed.json", {}).get("generated", ""))):
        if d > TODAY:
            sys.exit("run_stats.json run_date %s is older than %s (%s); set it to this run's date" % (TODAY, name, d))
    # step 4b's "page read, wording gone" records count only if 4b ran against the same previous run
    gone = cd.get("entries", []) if os.path.abspath(cd.get("prev", "")) == os.path.abspath(PREV) else []
    hist = load("rr_removed.json", {"entries": []})["entries"]
    # a paper listed as R&R again is no longer "removed"
    hist = [h for h in hist if not any(same(h["title"], h["journal"], x["title"], x["journal"]) for x in cur)]
    n_new = 0
    for x in old:
        if any(same(x["title"], x["journal"], y["title"], y["journal"]) for y in cur):
            continue
        # x was listed in the previous run, so a history entry from an earlier exit is stale: it returned in between
        hist = [h for h in hist if not (same(x["title"], x["journal"], h["title"], h["journal"])
                                        and h["removed_date"] < TODAY)]
        if any(same(x["title"], x["journal"], h["title"], h["journal"]) for h in hist):
            continue
        urls = {a["source_url"] for a in x["authors"]}
        hist.append(dict(title=x["title"], journal=x["journal"],
                         authors=[dict(name=a["name"], source_url=a["source_url"]) for a in x["authors"]],
                         last_listed=max(a["checked_date"] for a in x["authors"]), removed_date=TODAY,
                         paper_url=x.get("paper_url", ""), status="pending", evidence="", checked_date="",
                         wording_gone=[g for g in gone if g["source_url"] in urls
                                       and same(g["title"], g["journal"], x["title"], x["journal"])]))
        n_new += 1
    bad = [v for v in verdicts if not valid(v)]
    verdicts = [v for v in verdicts if valid(v)]
    todo, used = [], set()
    for h in hist:
        prior = h["status"]
        # a verdict counts for this exit only if made on or after the run in which the paper left the list
        vs = [(v["checked_date"], k, v) for k, v in enumerate(verdicts)
              if same(h["title"], h["journal"], v["title"], v["journal"]) and v["checked_date"] >= h["removed_date"]]
        used |= {k for _, k, _ in vs}
        v = max(vs, key=lambda t: t[:2])[2] if vs else None
        if (v or {}).get("status", prior) == "not_removed":
            h.update(status="not_removed", evidence=v["evidence"] if v else h["evidence"],
                     checked_date=v["checked_date"] if v else h["checked_date"])
            continue
        try:
            hit, other, queried = crossref(h)
        except Exception as err:
            print("crossref error, status kept: %s | %s" % (type(err).__name__, h["title"]))
            if prior == "pending":
                todo.append(dict(h, note="Crossref error %s this run; run 5b again" % type(err).__name__))
            continue
        note = ""
        if hit:
            h.update(status="published", evidence=hit, checked_date=TODAY)
        elif v and v["status"] == "presumed_rejected" and not (h.get("wording_gone") and queried and not other):
            note = ("presumed_rejected refused: needs step 4b's record that this paper's page was read with the "
                    "wording gone, and a Crossref search this run that found the paper in no journal")
            h.update(status="pending", evidence="", checked_date="")
        elif h["status"] == "presumed_rejected" and not v:
            # the verdict behind it was withdrawn: back to review
            note = "presumed_rejected verdict no longer in removed_review.json"
            h.update(status="pending", evidence="", checked_date="")
        elif v:
            h.update(status=v["status"], evidence=v["evidence"], checked_date=v["checked_date"])
        if h["status"] == "pending" or note:
            todo.append(dict(h, crossref_hints=other, note=note,
                             same_page_entries_now=[y["title"] for y in cur if y["journal"] == h["journal"]
                                                    and {a["source_url"] for a in h["authors"]} &
                                                    {a["source_url"] for a in y["authors"]}]))
        doi = re.search(r"doi:(10\.\S+)", h["evidence"])
        if h["status"] in ("published", "published_elsewhere") and doi:
            h["paper_url"] = "https://doi.org/" + doi.group(1).rstrip(".,;)")
    hist.sort(key=lambda h: (h["removed_date"], h["journal"], h["title"].lower()), reverse=True)
    for h in hist:
        print("%s | %s | %s | %s" % (h["status"], h["journal"], h["authors"][0]["name"], h["title"]))
    json.dump({"generated": TODAY, "entries": hist}, open(os.path.join(DATA, "rr_removed.json"), "w"),
              indent=1, ensure_ascii=False)
    unmatched = [v for k, v in enumerate(verdicts) if k not in used]
    json.dump(dict(papers=todo, invalid_verdicts=bad, unmatched_verdicts=unmatched), open(os.path.join(DATA, "removed_to_review.json"), "w"),
              indent=1, ensure_ascii=False)
    for v in bad:
        print("invalid verdict ignored:", json.dumps(v, ensure_ascii=False)[:200])
    for v in unmatched:
        print("verdict matches no paper that left the list on or before its date:", json.dumps(v, ensure_ascii=False)[:200])
    print("left the list this run %d; history %d (shown %d, waiting for review %d)"
          % (n_new, len(hist), sum(h["status"] in SHOWN for h in hist), len(todo)))


if __name__ == "__main__":
    main()
