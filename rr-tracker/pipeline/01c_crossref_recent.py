#!/usr/bin/env python3
"""Step 1c: recent top-5 accounting articles from Crossref, for weekly runs.

Step 1's OpenAlex list queries need ~200 requests, and the free OpenAlex budget is shared and often spent.
Crossref is queried instead, by journal ISSN, for journal articles first published on or after argv[1]
(default: 21 days ago). The DOIs are written in the same CSV layout as the author's local DOI lists
(<J>_DOIs_By_Year/<J>_<year>.csv) into data/crossref_recent/, so `01b_local_dois.py data/crossref_recent`
adds any that are missing from the cohort, by OpenAlex singleton lookups.
"""
import csv, datetime, os, sys, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "crossref_recent")
ISSN = {"JAE": "0165-4101", "JAR": "0021-8456", "TAR": "0001-4826", "CAR": "0823-9150", "RAST": "1380-6653"}
SINCE = sys.argv[1] if len(sys.argv) > 1 else (datetime.date.today() - datetime.timedelta(days=21)).isoformat()


def main():
    tot = 0
    for j, issn in ISSN.items():
        rows, cursor = [], "*"
        while cursor:
            r = requests.get("https://api.crossref.org/journals/%s/works" % issn,
                             params={"filter": "from-pub-date:%s,type:journal-article" % SINCE, "rows": 200,
                                     "cursor": cursor, "select": "DOI,title,issued", "mailto": "tanglin817@gmail.com"},
                             headers={"User-Agent": "shibaoliu.github.io RR tracker (mailto:tanglin817@gmail.com)"},
                             timeout=60)
            r.raise_for_status()
            m = r.json()["message"]
            rows += m["items"]
            cursor = m.get("next-cursor") if m["items"] else None
            time.sleep(0.3)
        by_year = {}
        for it in rows:
            y = ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0] or int(SINCE[:4])
            by_year.setdefault(max(2021, min(2026, int(y))), []).append(it)
        os.makedirs(os.path.join(OUT, "%s_DOIs_By_Year" % j), exist_ok=True)
        for y, its in by_year.items():
            with open(os.path.join(OUT, "%s_DOIs_By_Year" % j, "%s_%d.csv" % (j, y)), "w", newline="") as f:
                w = csv.writer(f); w.writerow(["Year", "Title", "DOI"])
                for it in its:
                    w.writerow([y, (it.get("title") or [""])[0], it["DOI"]])
        print("%s: %d articles since %s" % (j, len(rows), SINCE))
        tot += len(rows)
    print("total %d" % tot)


if __name__ == "__main__":
    main()
