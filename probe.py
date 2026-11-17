"""probe.py URL MATCHTYPE [REGEX] [extra k=v ...]: one CDX call, prints count, year spread, sample. Used to test leads."""
import sys, json, time, collections, urllib.parse, urllib.request
url, mt = sys.argv[1], sys.argv[2]
rx = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
q = [('url', url), ('matchType', mt), ('output', 'json'), ('fl', 'timestamp,original,mimetype,statuscode'), ('limit', '20000'),
     ('filter', 'statuscode:200'), ('collapse', 'digest')]
if rx: q.append(('filter', f'original:(?i){rx}'))
for kv in sys.argv[4:]: q.append(tuple(kv.split('=', 1)))
try:
    b = urllib.request.urlopen(urllib.request.Request('https://web.archive.org/cdx/search/cdx?' + urllib.parse.urlencode(q),
        headers={'User-Agent': 'research-lookup/0.1'}), timeout=240).read().decode('utf-8', 'replace')
except Exception as e:
    print('ERROR', getattr(e, 'code', ''), e); sys.exit(1)
d = json.loads(b) if b.strip() else []
rows = d[1:]
print(url, mt, 'rows', len(rows), dict(sorted(collections.Counter(r[0][:4] for r in rows).items())))
for r in rows[:: max(1, len(rows) // 12)][:12]: print('  ', r[0], r[2], r[1][:150])
