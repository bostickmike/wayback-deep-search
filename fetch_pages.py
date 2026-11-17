"""Fetch the archived pages the deep search found and keep only extracted rows (2026-11-16: "extracted rows only").

Queue: fetch_queue.tsv (summarize.py, from the deep search's results and the board surveys' index listings) plus
queue_extra.tsv (stage A below). Each archived version is fetched once as Wayback's raw capture (`id_` URL), passed to
extract.py, and dropped: no page body is written anywhere. Versions with the same content digest are fetched once.

Stage A: for each AppliTrack board (applitrack_slugs.txt), ask the CDX index for its archived job-listing pages
(onlineapp/jobpostings/Output.asp: the titles that the board's front page loads by script) -> queue_extra.tsv.
Stage B: fetch in order pay documents, single posting pages, AppliTrack listings, then vacancy pages.

Outputs (per target, so no file grows past GitHub's limits):
  extracted/pages/<target>.tsv  one row per fetched version: status, size, sha1, title, counts, note
  extracted/lines/<target>.tsv  one row per candidate line: kind (job/pay), text, date in text, link
  fetched.tsv                   wayback_url of every version handled (resume list); log: fetch_pages.log
  failed.tsv                    one line per failed try; a version that failed in two runs is left out
Polite: 5 s between requests, backs off on 429/503/504, stops after 3 throttled answers in a row; DEADLINE (epoch
seconds, set by the workflow) ends a run between requests. Run: python3 -I fetch_pages.py
"""
import csv, hashlib, json, os, re, sys, time, urllib.parse, urllib.request
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
from extract import extract

UA = {'User-Agent': 'research-lookup/0.1'}
DEADLINE = float(os.environ.get('DEADLINE', '0'))
MAX_BYTES = 25 * 1024 * 1024
LOG = open('fetch_pages.log', 'a')
def log(*a): print(time.strftime('%F %T'), *a, file=LOG, flush=True)

throttled = 0
def request(url, timeout=120):
    """(status, body) or (None, None) after 3 failed tries; exits on deadline or 3 throttles in a row."""
    global throttled
    for k in range(3):
        if DEADLINE and time.time() > DEADLINE:
            log('== stopping: chunk time limit (rerun to resume)'); sys.exit(0)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                body = r.read(MAX_BYTES + 1)
                status = r.status
            throttled = 0; time.sleep(5)
            return status, body
        except urllib.error.HTTPError as e:
            if e.code in (404, 403, 410):   # capture missing or blocked: a result, not a failure
                throttled = 0; time.sleep(5); return e.code, b''
            code = e.code; msg = str(e)
        except Exception as e:
            code = None; msg = str(e)
        log('error', url[:150], code, msg[:120])
        if code in (429, 503, 504) or 'timed out' in msg.lower() or 'offline' in msg.lower():
            throttled += 1
            if throttled >= 3: log('== stopping: throttled 3 times in a row (rerun to resume)'); sys.exit(0)
        time.sleep(120 * (k + 1))
    return None, None

def safe(name): return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')[:80] or 'unknown'

# ---- stage A: AppliTrack listing pages from the CDX index -------------------------------------------------------
QCOLS = ['target', 'state', 'class', 'timestamp', 'original', 'mimetype', 'digest', 'wayback_url']
done_a = set(l.strip() for l in open('applitrack_done.txt')) if os.path.exists('applitrack_done.txt') else set()
slugs = [l.split()[0] for l in open('applitrack_slugs.txt') if l.strip() and not l.startswith('#')]
for slug in slugs:
    if slug in done_a: continue
    q = [('url', f'applitrack.com/{slug}/onlineapp/jobpostings/output.asp'), ('matchType', 'prefix'),
         ('output', 'json'), ('fl', 'timestamp,original,mimetype,digest'), ('filter', 'statuscode:200'),
         ('collapse', 'digest'), ('limit', '20000')]
    status, body = request('https://web.archive.org/cdx/search/cdx?' + urllib.parse.urlencode(q), 240)
    if status != 200: log('applitrack cdx failed', slug, status); continue
    data = json.loads(body) if body.strip() else []
    new = not os.path.exists('queue_extra.tsv')
    with open('queue_extra.tsv', 'a') as out:
        if new: out.write('\t'.join(QCOLS) + '\n')
        for ts, orig, mime, dig in data[1:]:
            out.write('\t'.join([f'applitrack:{slug}', '', 'applitrack_list', ts, orig, mime, dig,
                                 f'https://web.archive.org/web/{ts}id_/{orig}']) + '\n')
    with open('applitrack_done.txt', 'a') as d: d.write(slug + '\n')
    log('applitrack', slug, len(data[1:]) if data else 0, 'listing versions')

# ---- stage B: fetch and extract ----------------------------------------------------------------------------------
queue = []
for f in ('fetch_queue.tsv', 'queue_extra.tsv'):
    if os.path.exists(f): queue += list(csv.DictReader(open(f), delimiter='\t'))
ORDER = {'pay': 0, 'posting_page': 1, 'applitrack_list': 2, 'vacancy': 3}
queue.sort(key=lambda r: (ORDER.get(r['class'], 9), r['target'], r['timestamp']))
fetched = set(l.split('\t')[0].strip() for l in open('fetched.tsv')) if os.path.exists('fetched.tsv') else set()
by_digest = {}   # digest -> target file rows already written (same content: record the version, don't refetch)
if os.path.exists('fetched.tsv'):
    for l in open('fetched.tsv'):
        p = l.rstrip('\n').split('\t')
        if len(p) > 1 and p[1]: by_digest[p[1]] = p[0]
os.makedirs('extracted/pages', exist_ok=True); os.makedirs('extracted/lines', exist_ok=True)
PCOLS = ['target', 'state', 'class', 'timestamp', 'original', 'mimetype', 'digest', 'http_status', 'bytes', 'sha1',
         'title', 'text_chars', 'job_lines', 'pay_lines', 'same_content_as', 'note']
LCOLS = ['target', 'class', 'timestamp', 'original', 'kind', 'text', 'date_in_text', 'link']
def append(path, cols, rows):
    new = not os.path.exists(path)
    with open(path, 'a', newline='') as out:
        w = csv.writer(out, delimiter='\t', lineterminator='\n')
        if new: w.writerow(cols)
        for r in rows: w.writerow([str(r.get(c, '')).replace('\t', ' ').replace('\n', ' ') for c in cols])
failed = {}
if os.path.exists('failed.tsv'):
    for l in open('failed.tsv'): u = l.split('\t')[0].strip(); failed[u] = failed.get(u, 0) + 1
gave_up = {u for u, k in failed.items() if k >= 2}   # failed in two runs: left out (listed in failed.tsv)
todo = [r for r in queue if r['wayback_url'] not in fetched and r['wayback_url'] not in gave_up]
log(f'== run start: queue {len(queue)}, done {len(fetched)}, to do {len(todo)}')
n = 0
for r in todo:
    url, dig, name = r['wayback_url'], r.get('digest', ''), safe(r['target'])
    page = {k: r.get(k, '') for k in ('target', 'state', 'class', 'timestamp', 'original', 'mimetype', 'digest')}
    if dig and dig in by_digest:
        page['same_content_as'] = by_digest[dig]
        append(f'extracted/pages/{name}.tsv', PCOLS, [page])
    else:
        status, body = request(url)
        if status is None:
            log('gave up', url[:150])
            with open('failed.tsv', 'a') as d: d.write(f"{url}\t{time.strftime('%F %T')}\n")
            continue
        page['http_status'] = status
        page['bytes'] = len(body)
        if len(body) > MAX_BYTES: page['note'] = 'over 25 MB, not extracted'
        elif body:
            page['sha1'] = hashlib.sha1(body).hexdigest()
            info, lines = extract(body, r.get('mimetype', ''), r['original'])
            page.update(info)
            append(f'extracted/lines/{name}.tsv', LCOLS,
                   [dict(l, target=r['target'], **{'class': r['class']}, timestamp=r['timestamp'], original=r['original'])
                    for l in lines])
        append(f'extracted/pages/{name}.tsv', PCOLS, [page])
        if dig: by_digest[dig] = url
    with open('fetched.tsv', 'a') as d: d.write(f"{url}\t{dig}\n")
    fetched.add(url); n += 1
    if n % 100 == 0: log('progress', n, 'this run;', len(fetched), 'of', len(queue))
left = {q['wayback_url'] for q in queue} - fetched - gave_up
log('== finished: every queued version fetched' if not left else f'== run end: {len(left)} left')
