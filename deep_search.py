"""Wayback deep search (2026-11-16).

Earlier surveys (2026-11-14_wy-history/board_survey.py, 2026-11-15_mt-boards/) queried only known job-board URLs by
prefix. This one asks the CDX index for every job- or pay-related URL anywhere on each district's own domain
(matchType=domain, so subdomains too), on the old shared state domains (k12.mt.us, k12.wy.us) and on statewide
education bodies' sites; HTML and documents (PDF/Word/Excel), status 200, collapse=digest (one row per content
change), paged with resume keys.

Stage 1: MT district websites from NCES district pages (WY's are in wy_nces_websites.tsv).
Stage 2: one CDX sweep per target -> results/<target>.tsv; done.tsv makes it resumable.
Polite: 8 s between CDX calls (the board fetch also uses Wayback), backs off on 429/503/timeouts, and stops after
3 throttled answers in a row (rerun to resume). Log: deep_search.log. Run: python3 -I deep_search.py
On GitHub Actions (.github/workflows/wayback.yml) the DEADLINE env var ends each run between calls.
"""
import csv, json, os, re, sys, time, urllib.parse, urllib.request

os.chdir(os.path.dirname(os.path.abspath(__file__)))
UA = {'User-Agent': 'research-lookup/0.1'}
LOG = open('deep_search.log', 'a')
DEADLINE = float(os.environ.get('DEADLINE', '0'))   # epoch seconds; 0 = no limit (set by the workflow)
def log(*a):
    print(time.strftime('%F %T'), *a, file=LOG, flush=True)

def get(url, timeout=180):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode('utf-8', 'replace')

# ---- stage 1: MT websites from NCES ------------------------------------------------------------------------------
if not os.path.exists('mt_nces_websites.tsv'):
    ids = json.loads(get('https://educationdata.urban.org/api/v1/school-districts/ccd/directory/2023/?fips=30'))['results']
    with open('mt_nces_websites.tsv.tmp', 'w') as out:
        for r in ids:
            w = ''
            try:
                page = get(f"https://nces.ed.gov/ccd/districtsearch/district_detail.asp?ID2={r['leaid']}", 60)
                ws = [u for u in re.findall(r'https?://[a-z0-9./-]+', page, re.I)
                      if not re.search(r'nces|ed\.gov|census|w3\.org|google|facebook|twitter', u, re.I)]
                w = ws[0] if ws else ''
            except Exception as e:
                log('nces failed', r['leaid'], e)
            out.write(f"{r['leaid']}\t{r['lea_name']}\t{w}\n")
            time.sleep(2)
    os.rename('mt_nces_websites.tsv.tmp', 'mt_nces_websites.tsv')
    log('stage 1 done', len(ids), 'MT LEAs')

# ---- targets -----------------------------------------------------------------------------------------------------
NOT_DISTRICT = re.compile(r'wdh\.state|cathedralhome|stjoseph|redtopmeadows|dfs\.wyo|youthemergency|wbihelp|riteofpassage|'
                          r'acrobat\.adobe|aptg\.co|nationalmap|biomimicry|canva\.com|familyoutreach|gabbart|parentsquare|'
                          r'jotform|lander\.k12\.nv|northidaho|opendatacommons|taleo|studentaidcalculator|neoed|submittable|'
                          r'westernwyoming\.edu|wyotech|wyva\.k12\.com|^x\.edu|youtu\.be|allthrive|mt\.gov$|state\.mt\.us$', re.I)
# Website companies: search the district's own host, not the company's whole domain (schoolloop.com alone is 5,581
# index pages, every School Loop school in the US; 2026-11-18). wixsite.com: 16,066 index pages, every Wix site in
# the world, ~50 a 5-hour run; the one MT/WY district on it is Absarokee (hgunderson6.wixsite.com; 2026-11-22).
VENDOR_HOSTED = re.compile(r'\.(sharpschool|schoolinsites|schoolloop|schoolwebpages|schoolwires|wixsite)\.(com|net)$')
def target_of(host):
    h = re.sub(r'^www\.', '', host.lower().strip().strip('/'))
    h = re.sub(r'^https?://', '', h).split('/')[0].split(':')[0]
    if not h or NOT_DISTRICT.search(h): return None
    if re.search(r'\.k12\.(mt|wy)\.us$', h): return None          # covered by the two state-domain sweeps
    if VENDOR_HOSTED.search(h): return (h, 'host')
    return ('.'.join(h.split('.')[-2:]), 'domain')

targets = {}
def add(host, why):
    t = target_of(host)
    if t and t not in targets: targets[t] = why
for f, why in (('district_hosts.txt', 'repo/notes URL'),):
    for l in open(f): add(l, why)
for f in ('wy_nces_websites.tsv', 'mt_nces_websites.tsv'):
    for r in csv.reader(open(f), delimiter='\t'):
        if len(r) > 2 and r[2]: add(r[2], 'NCES website')
# State domains and statewide bodies (some are guesses; a domain with no captures just returns nothing).
for t, why in [(('k12.mt.us', 'domain'), 'old MT shared district domain'),
               (('k12.wy.us', 'domain'), 'old WY shared district domain (also old WDE)'),
               (('opi.state.mt.us', 'domain'), 'OPI old domain'), (('opi.mt.gov', 'host'), 'OPI (apps.opi board surveyed before)'),
               (('edu.wyoming.gov', 'domain'), 'WDE'), (('wsba-wy.org', 'domain'), 'WSBA'),
               (('mtsba.org', 'domain'), 'MT School Boards Assn'), (('sammt.org', 'domain'), 'School Administrators of MT'),
               (('mrea-mt.org', 'domain'), 'MT Rural Education Assn'), (('mea-mft.org', 'domain'), 'MEA-MFT (MT union)'),
               (('wyoea.org', 'domain'), 'WY Education Assn'), (('wasa-wy.org', 'domain'), 'WY school administrators (guess)'),
               (('mcasemt.org', 'domain'), 'MT council of school admin (guess)'), (('teachmontana.org', 'domain'), 'guess'),
               (('teachwyoming.org', 'domain'), 'guess'), (('wyomingboces.org', 'domain'), 'guess')]:
    targets.setdefault(t, why)
with open('targets.tsv', 'w') as out:
    out.write('target\tmatchType\twhy\n')
    for (t, m), why in sorted(targets.items()): out.write(f'{t}\t{m}\t{why}\n')
log('targets', len(targets))

# ---- stage 2: CDX sweeps -----------------------------------------------------------------------------------------
WORDS = (r'employ|job|career|vacanc|position|personnel|human.?resource|/hr[/._-]|opening|posting|hiring|recruit|'
         r'salar|wage|compensat|negotiat|master.?agreement|collective.?bargain|pay.?scale|pay.?schedule|'
         r'certified.?staff|classified.?staff|applitrack|tedk12|schoolspring')
FILTERS = ['statuscode:200', f'original:(?i).*({WORDS}).*',
           '!mimetype:(image/.*|text/css|.*javascript.*|font/.*|.*woff.*|video/.*|audio/.*)']
STATE_RX = r'.*(montana|wyoming|state=(mt|wy)|/mt/|/wy/|_mt_|_wy_).*'
SPECIAL = {  # target -> its own URL filter (aggregators: state pages only; associations: openings pages)
    ('k12jobspot.com', 'domain'): STATE_RX, ('schoolspring.com', 'domain'): STATE_RX,
    ('teachers-teachers.com', 'domain'): STATE_RX, ('higheredjobs.com', 'domain'): STATE_RX,
    ('sammt.org', 'domain'): r'.*(job|employ|vacanc|position|opening|search).*',
    ('mtsba.org', 'domain'): r'.*(administrativeopenings|adminopenings|currentopenings|suptopenings|openings|vacanc|search).*'}
for k in SPECIAL: targets.setdefault(k, 'aggregator/association (lead from probes 11-16)')
os.makedirs('results', exist_ok=True)
done = set(l.split('\t')[0] for l in open('done.tsv')) if os.path.exists('done.tsv') else set()
throttled = 0
def cdx(q, too_big_ok=False):
    """One CDX call with backoff; None after 3 tries; exits after 3 throttles in a row (rerun resumes)."""
    global throttled
    for k in range(3):
        if DEADLINE and time.time() > DEADLINE:   # GitHub Actions run's time budget: stop between calls
            log('== stopping: chunk time limit (rerun to resume)'); sys.exit(0)
        try:
            body = get('https://web.archive.org/cdx/search/cdx?' + urllib.parse.urlencode(q), 240)
            if 'Temporarily Offline' in body: raise IOError('temporarily offline')
            throttled = 0
            time.sleep(8)
            return body
        except Exception as e:
            code = getattr(e, 'code', None)
            log('error', dict(q).get('url'), dict(q).get('page', ''), code, str(e)[:120])
            if too_big_ok and (code == 504 or 'IncompleteRead' in str(e) or 'timed out' in str(e).lower()):
                return None   # site too big for one query: the caller switches to page mode
            if code in (429, 503, 504) or 'offline' in str(e).lower() or 'timed out' in str(e).lower():
                throttled += 1
                if throttled >= 3:
                    log('== stopping: throttled 3 times in a row (rerun to resume)'); sys.exit(0)
            time.sleep(300 * (k + 1))
    return None
def base_q(t, m, rx):
    return [('url', t), ('matchType', m), ('output', 'json'), ('fl', 'urlkey,timestamp,original,mimetype,digest,length'),
            ('filter', 'statuscode:200'), ('filter', f'original:(?i){rx}'), ('filter', FILTERS[2]), ('collapse', 'digest')]
# Archived URLs can carry credentials in their query (a Google OAuth token in a k12.mt.us link stopped the 11-23
# push at GitHub's secret scanning). The value is replaced before a row is saved; the parameter name stays.
SECRET_PARAM = re.compile(r'(?i)([?&;](?:access_token|id_token|refresh_token|oauth_token|token|api_?key|sig|signature|'
                          r'password|passwd|pwd|secret|client_secret|auth)=)[^&#;\s"\'<>]+')
GOOGLE_TOKEN = re.compile(r'ya29\.[0-9A-Za-z_\-]{20,}')
def mask_secrets(s):
    return GOOGLE_TOKEN.sub('ya29.REDACTED', SECRET_PARAM.sub(r'\1REDACTED', s))
def fname(t): return f"results/{re.sub(r'[^a-z0-9]+', '_', t)}.tsv"
def write_rows(t, rows, mode):
    new = mode == 'w' or not os.path.exists(fname(t))
    with open(fname(t), 'a' if not new else 'w') as out:
        if new: out.write('urlkey\ttimestamp\toriginal\tmimetype\tdigest\tlength\n')
        for r in rows: out.write(mask_secrets('\t'.join(r)) + '\n')
BIG = {'k12.mt.us', 'k12.wy.us', 'opi.state.mt.us', 'opi.mt.gov'}   # page mode (showNumPages: 2027, 130, 1185, 3210)
def npages(t, m):
    b = cdx([('url', t), ('matchType', m), ('showNumPages', 'true')])
    try: return int(b.strip())
    except Exception: return None
def sweep_paged(t, m, rx):
    n = npages(t, m)
    if n is None: log('no page count', t); return False
    prog = f"results/.{re.sub(r'[^a-z0-9]+', '_', t)}.page"
    start = int(open(prog).read()) if os.path.exists(prog) else 0
    if start == 0: write_rows(t, [], 'w')
    for pg in range(start, n):
        body = cdx(base_q(t, m, rx) + [('page', str(pg))])
        if body is None: log('gave up', t, 'page', pg); return False
        data = json.loads(body) if body.strip() else []
        write_rows(t, data[1:] if data else [], 'a')
        open(prog, 'w').write(str(pg + 1))
        if pg % 50 == 0: log('progress', t, pg, '/', n)
    return n
def sweep_simple(t, m, rx):
    """One query with resume keys; None if it fails (then page mode)."""
    rows, resume = [], None
    while True:
        q = base_q(t, m, rx) + [('limit', '5000'), ('showResumeKey', 'true')] + ([('resumeKey', resume)] if resume else [])
        body = cdx(q, too_big_ok=True)
        if body is None: return None
        data = json.loads(body) if body.strip() else []
        page = data[1:] if data else []
        resume = None
        if len(page) >= 2 and page[-2] == []: resume = page[-1][0]; page = page[:-2]
        rows += page
        if not resume: break
    write_rows(t, rows, 'w')
    return len(rows)
order = sorted(targets, key=lambda k: (k[0] in BIG, k[0]))
for (t, m) in order:
    if t in done: continue
    rx = SPECIAL.get((t, m), f'.*({WORDS}).*')
    if t in BIG: r = sweep_paged(t, m, rx); how = 'pages'
    else:
        r = sweep_simple(t, m, rx); how = 'rows'
        if r is None: log('simple query failed, trying page mode', t); r = sweep_paged(t, m, rx); how = 'pages'
    if r is False or r is None: continue
    with open('done.tsv', 'a') as d: d.write(f'{t}\t{m}\t{how}:{r}\n')
    log('done', t, how, r)
log('== finished all targets')
