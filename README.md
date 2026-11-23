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
- `summarize.py`: sorts the rows into vacancy / pay / other and writes `catalog_by_target.tsv`, `catalog_urls.tsv`
  and `fetch_queue.tsv` (committed when the search finishes).
- `probe.py`: one CDX call, for testing a lead. `leads.tsv`: leads found that way.
- Inputs: `district_hosts.txt`, `wy_nces_websites.tsv`, `mt_nces_websites.tsv` (district websites from NCES), `wy_leaids.tsv`.

## Page fetch (after the search): extracted rows only
When the search finishes, `wayback.yml` runs `summarize.py` (vacancy pages, pay documents, single posting pages from
the board surveys' index listings in `board_cdx/`) and starts `fetch.yml`. `fetch_pages.py` first asks the index for
each AppliTrack board's archived listing pages (`applitrack_slugs.txt` -> `queue_extra.tsv`), then fetches every
queued version once (same digest = same content, fetched once), passes it to `extract.py`, and keeps only:
- `extracted/pages/<target>.tsv`: one row per version (HTTP status, size, SHA-1, title, counts);
- `extracted/lines/<target>.tsv`: candidate lines: `job` (reads like a job title or posting, with any date and its
  link) and `pay` (dollar figures or a salary-table row).
No archived page is stored. The rules are deliberately broad: the lines are candidates for later parsing and review.

## Running
GitHub Actions, `.github/workflows/wayback.yml`, started by hand (Actions tab, "Run workflow"). Each run searches
for `minutes`, commits its progress, and starts the next run until every target is done. Commit a file named `STOP`
to end the chain. Run only one Wayback job at a time.

**2026-11-18: website companies searched by district host.** `schoolloop.com`, `schoolwebpages.com`,
`schoolwires.com` and `schoolwires.net` had been whole-domain targets (one MT district's NCES website sits on each),
which meant every school those companies host: `schoolloop.com` alone is 5,581 index pages, and four 5-hour runs
got through 525 of them. They are now host targets, like SharpSchool and SchoolInSites: the 7 MT district sites
(Trinity, Custer, Lambert, Manhattan, Montana City, Red Lodge, Sidney). The partial whole-domain School Loop rows
are kept in `partial/` (outside `results/`, so `summarize.py` doesn't queue them).

**2026-11-22: `wixsite.com` too.** As a whole-domain target it was 16,066 index pages (every Wix site), about 50 a
5-hour run with many 503s/refusals, so the chain would have spent weeks there. The one MT/WY district site on it,
Absarokee (`hgunderson6.wixsite.com`), is now a host target. The partial whole-domain rows
(`results/wixsite_com.tsv`, 1,350 index pages in) are to be moved to `partial/` between runs.
