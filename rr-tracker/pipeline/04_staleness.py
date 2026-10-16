#!/usr/bin/env python3
"""Step 4: second staleness route (Crossref) for R&R candidates.

Step 3 already compares each title with the six journals' 2021-2026 articles in OpenAlex. This step asks
Crossref, for every candidate with a title of >= 4 words, whether a journal article with a near-identical
title (difflib ratio >= 0.90) AND the candidate author's family name among its authors already exists in ANY
journal. A hit means the page's "R&R" line is out of date (accepted/published since), so the candidate is
dropped from the public table. Crossref's public API is used with a mailto (its "polite pool").
Input/Output: data/rr_candidates.json (adds crossref_match, crossref_checked)
"""
import difflib, json, os, re, time, unicodedata
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "data", "rr_candidates.json")
UA = "shibaoliu.github.io RR tracker (mailto:tanglin817@gmail.com)"


def nz(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", s)).strip()


def family(display):
    t = nz(display).split()
    return t[-1] if t else ""


def check(title, author):
    r = requests.get("https://api.crossref.org/works",
                     params={"query.bibliographic": title, "rows": 8, "filter": "type:journal-article",
                             "select": "DOI,title,author,container-title,issued", "mailto": "tanglin817@gmail.com"},
                     headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    fam = family(author)
    for it in r.json()["message"]["items"]:
        t = (it.get("title") or [""])[0]
        if difflib.SequenceMatcher(None, nz(t), nz(title)).ratio() < 0.90:
            continue
        fams = {nz(a.get("family", "")).split()[-1] for a in it.get("author", []) if nz(a.get("family", ""))}
        if fam and fam in fams:
            y = (it.get("issued", {}).get("date-parts") or [[None]])[0][0]
            return "%s (%s) doi:%s" % ((it.get("container-title") or [""])[0], y, it["DOI"])
    return ""


def main():
    cands = json.load(open(P))
    n = hits = 0
    for c in cands:
        if c.get("crossref_checked") or len(nz(c["title"]).split()) < 4 or c["title"] == "unknown":
            continue
        try:
            c["crossref_match"] = check(c["title"], c["author_name"])
            c["crossref_checked"] = time.strftime("%Y-%m-%d")
        except Exception as e:
            c["crossref_match"], c["crossref_checked"] = "", ""
            print("error", c["candidate_id"], type(e).__name__)
        n += 1
        hits += bool(c["crossref_match"])
        time.sleep(0.2)
    json.dump(cands, open(P, "w"), indent=1, ensure_ascii=False)
    print("checked %d candidates against Crossref; %d already published" % (n, hits))


if __name__ == "__main__":
    main()
