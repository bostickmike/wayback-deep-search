# Wayback deep search: Montana and Wyoming school jobs

A catalog of what the Internet Archive's Wayback Machine holds about past K-12 job postings and pay in Montana and
Wyoming: for each district website, the old shared state domains (k12.mt.us, k12.wy.us), the state education
agencies and statewide associations, every archived URL that looks job- or pay-related.

Only Wayback **index** rows are saved here (from the CDX API: URL key, capture timestamp, original URL, MIME type,
content digest, length; one row per content change). No archived pages are stored.

## Files
- `deep_search.py`: the search. Per target, one CDX query (`matchType=domain`, status 200, a job/pay URL filter,
  images/CSS/JS excluded, `collapse=digest`), or CDX page mode for the four largest domains. 8 s between calls, backs
  off on 429/503/504, stops after 3 throttled answers in a row. Resumable from `done.tsv` and `results/.<target>.page`.
- `targets.tsv`: the targets and why each is included. `done.tsv`: finished targets with row or page counts.
- `results/<target>.tsv`: the index rows. `deep_search.log`: progress and errors.
- `summarize.py`: sorts the rows into vacancy / pay / other and writes catalogs and a fetch queue (not committed).
- `probe.py`: one CDX call, for testing a lead. `leads.tsv`: leads found that way.
- Inputs: `district_hosts.txt`, `wy_nces_websites.tsv`, `mt_nces_websites.tsv` (district websites from NCES), `wy_leaids.tsv`.

## Running
GitHub Actions, `.github/workflows/wayback.yml`, started by hand (Actions tab, "Run workflow"). Each run searches
for `minutes`, commits its progress, and starts the next run until every target is done. Commit a file named `STOP`
to end the chain. Run only one Wayback job at a time.
