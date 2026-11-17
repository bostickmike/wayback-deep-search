"""Sort the deep search's rows (results/*.tsv) into a catalog and a fetch queue. Run any time: python3 -I summarize.py

Each saved URL version is classed by its address (no page fetched yet):
  vacancy  lists or single postings: vacanc, opening, posting, job(s), careers/employment pages, applitrack/tedk12 links
  pay      salary schedules, negotiated agreements, compensation
  noise    student career/CTE pages, handbooks, policies, benefits, feeds, wp-json/oembed, forms/applications
Writes:
  catalog_by_target.tsv  one row per target: versions by class, years covered, first/last
  catalog_urls.tsv       one row per (target, class, address) for vacancy and pay: versions, first, last, years
  fetch_queue.tsv        one row per version to fetch (vacancy + pay), with its Wayback id_ URL; the slow-fetch queue
"""
import csv, collections, glob, os, re

os.chdir(os.path.dirname(os.path.abspath(__file__)))
NOISE = re.compile(r'college[-_ ]?career|career[-_ ]?(tech|center|cluster|pathway|day|fair|ready|readiness|explor)|\bcte\b|'
                   r'handbook|polic(y|ies)|benefit|insurance|retire|acceptable[-_]use|wp-json|oembed|/feed/?$|\.rss|rss\+xml|'
                   r'application[-_ ]?(form|packet)|employ\w*[-_]?app(lication)?\b|w-?4|i-?9|direct[-_]?deposit|'
                   r'login|signin|calendar|newsletter|minutes|agenda|board[-_]?meeting|covid|reopen|student[-_]?employ',
                   re.I)
PAY = re.compile(r'salar|wage|compensat|negotiat|master[-_ ]?agreement|bargain|pay[-_ ]?(scale|schedule)|'
                 r'certified[-_ ]?staff[-_ ]?(salary|schedule)|classified[-_ ]?(salary|schedule)', re.I)
VAC = re.compile(r'vacanc|opening|posting|job|career|employment|position|hiring|recruit|personnel|human[-_ ]?resource|'
                 r'/hr[/._-]|applitrack|tedk12|schoolspring|adminopenings|suptopenings', re.I)

def klass(url, mime):
    u = url.lower()
    if NOISE.search(u) or mime.startswith(('image/', 'text/css')) or 'javascript' in mime: return 'noise'
    if PAY.search(u): return 'pay'
    if VAC.search(u): return 'vacancy'
    return 'noise'

def state_of(target):
    if target.endswith(('.wy.us', 'wyoming.gov')) or 'wy' in target.split('.')[0][-3:]: return 'WY?'
    return ''

targets = {r['target']: r for r in csv.DictReader(open('targets.tsv'), delimiter='\t')}
wy = {re.sub(r'^https?://(www\.)?', '', r[2]).split('/')[0].lower() for r in csv.reader(open('wy_nces_websites.tsv'), delimiter='\t') if len(r) > 2 and r[2]}
wy_dom = {'.'.join(h.split('.')[-2:]) for h in wy}

by_target, urls, queue = [], collections.defaultdict(list), []
for f in sorted(glob.glob('results/*.tsv')):
    rows = list(csv.DictReader(open(f), delimiter='\t'))
    if not rows: continue
    t = rows[0]['urlkey'].split(')')[0]
    t = '.'.join(reversed(t.split(','))) if t else os.path.basename(f)[:-4]
    name = os.path.basename(f)[:-4]
    st = 'WY' if (any(name == re.sub(r'[^a-z0-9]+', '_', d) for d in wy_dom) or 'wy_us' in name or 'wyoming' in name) else 'MT/other'
    c = collections.Counter(); yrs = collections.defaultdict(set)
    for r in rows:
        k = klass(r['original'], r['mimetype']); c[k] += 1; yrs[k].add(r['timestamp'][:4])
        if k in ('vacancy', 'pay'):
            addr = re.sub(r'^https?://(www\.)?', '', r['original']).split('#')[0].rstrip('/').lower().replace(':80/', '/')
            urls[(name, st, k, addr)].append(r)
            queue.append((name, st, k, r['timestamp'], r['original'], r['mimetype'], r['digest'],
                          f"https://web.archive.org/web/{r['timestamp']}id_/{r['original']}"))
    by_target.append((name, st, len(rows), c['vacancy'], c['pay'], c['noise'],
                      ' '.join(sorted(yrs['vacancy'] | yrs['pay'])),
                      min((r['timestamp'][:8] for r in rows), default=''), max((r['timestamp'][:8] for r in rows), default='')))

# Board surveys' saved CDX listings (11-14/15): single posting pages and documents the list-page fetch skipped.
POST = re.compile(r'applitrackjobid=|jobid=|/job/|jobdetail|viewjob|posting_?id=|/jobs/\d', re.I)
seen_q = {(q[4], q[3]) for q in queue}
for state, d in (('WY', '../2026-11-14_wy-history/boards'), ('MT', '../2026-11-15_mt-boards/boards')):
    c = collections.Counter()
    for f in glob.glob(d + '/cdx_*.txt'):
        name = 'board:' + os.path.basename(f)[4:-4]
        for line in open(f):
            parts = line.split()
            if len(parts) < 3: continue
            ts, orig, mime = parts[0], parts[1], parts[2]
            if POST.search(orig) and 'html' in mime: k = 'posting_page'
            elif re.search(r'browsefile|\.pdf|\.docx?$', orig, re.I): k = klass(orig, mime)
            else: continue
            if k == 'noise' or (orig, ts) in seen_q: continue
            seen_q.add((orig, ts)); c[k] += 1
            addr = re.sub(r'^https?://(www\.)?', '', orig).split('#')[0].rstrip('/').lower().replace(':80/', '/')
            r = {'timestamp': ts, 'original': orig, 'mimetype': mime, 'digest': ''}
            urls[(name, state, k, addr)].append(r)
            queue.append((name, state, k, ts, orig, mime, '', f"https://web.archive.org/web/{ts}id_/{orig}"))
    print(state, 'board listings added:', dict(c))

with open('catalog_by_target.tsv', 'w') as out:
    out.write('target\tstate\tversions\tvacancy\tpay\tnoise\tyears_vacancy_or_pay\tfirst\tlast\n')
    for row in sorted(by_target, key=lambda x: -(x[3] + x[4])): out.write('\t'.join(map(str, row)) + '\n')
with open('catalog_urls.tsv', 'w') as out:
    out.write('target\tstate\tclass\taddress\tversions\tfirst\tlast\tyears\tmimetypes\n')
    for (name, st, k, addr), rs in sorted(urls.items(), key=lambda kv: (kv[0][0], kv[0][2], -len(kv[1]))):
        ts = sorted(r['timestamp'] for r in rs)
        out.write(f"{name}\t{st}\t{k}\t{addr}\t{len(rs)}\t{ts[0][:8]}\t{ts[-1][:8]}\t{' '.join(sorted({x[:4] for x in ts}))}\t"
                  f"{','.join(sorted({r['mimetype'] for r in rs}))}\n")
with open('fetch_queue.tsv', 'w') as out:
    out.write('target\tstate\tclass\ttimestamp\toriginal\tmimetype\tdigest\twayback_url\n')
    for q in sorted(queue): out.write('\t'.join(q) + '\n')
tot = collections.Counter()
for row in by_target: tot['targets'] += 1; tot['vacancy'] += row[3]; tot['pay'] += row[4]; tot['noise'] += row[5]
print(f"{tot['targets']} targets with results; versions: vacancy {tot['vacancy']}, pay {tot['pay']}, noise {tot['noise']}; "
      f"{len(urls)} distinct vacancy/pay addresses; fetch queue {len(queue)}")
