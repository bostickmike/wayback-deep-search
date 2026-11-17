"""Extract short rows from one archived page, without keeping the page (2026-11-16: "extracted rows only").

extract(body: bytes, mimetype: str, url: str) -> (page_info: dict, lines: list[dict])
  page_info: title, text length, counts. lines: one dict per candidate line, kind 'job' (a line that reads like a job
  title or posting, with any date in it and its link) or 'pay' (a line with dollar figures or a salary-schedule row).
Deterministic rules only, deliberately broad: the rows are candidates for later parsing and review, not final data.
Formats: HTML, RSS/Atom, PDF (pdftotext), DOCX. Others: page_info only.
"""
import html, io, re, subprocess, tempfile, zipfile
from html.parser import HTMLParser
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

MAX_LINE = 600   # salary-table rows are long; job lines are capped at 200 in classify()
JOB = re.compile(r'\b(teach(er|ing)|instructor|para(professional|educator)?s?\b|aide|tutor|substitute|principal|superintendent|'
                 r'counselor|librarian|coach(es|ing)?\b|custodian|janitor|maintenance|bus driver|driver|cook|food service|'
                 r'nurse|psycholog|speech|therap(ist|y)|secretary|clerk|bookkeeper|business manager|administrat|director|'
                 r'coordinator|specialist|technician|interpreter|sped|special ed|kindergarten|elementary|middle school|'
                 r'high school|grade|math|science|english|music|band|art\b|physical education|\bpe\b|cte|ag(riculture)?\b|'
                 r'vacanc|opening|position|job|employment|hiring|apply)', re.I)
NOT_JOB = re.compile(r'^(home|menu|search|login|log in|contact us|calendar|skip to|copyright|©|privacy|sitemap|back|next|'
                     r'previous|apply now|click here)\b', re.I)
DATE = re.compile(r'\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2},? \d{4}|'
                  r'\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b', re.I)
MONEY = re.compile(r'\$\s?\d[\d,]*(?:\.\d{2})?|\b\d{2},\d{3}(?:\.\d{2})?\b|\b\d{1,3}\.\d{2}\b')
SALARY_NUM = re.compile(r'(?<![\d.,])(?:[2-9]\d{4}|[1-3]\d{5})(?![\d.,])')   # bare 20000-399999: salary-table cells
SCHEDULE = re.compile(r'\b(step|lane|ba\+?\d*|ma\+?\d*|bachelor|master|salary|stipend|hourly|per hour|annual|base)\b', re.I)

def clean(s):
    s = html.unescape(re.sub(r'\s+', ' ', s or '')).strip()
    return s[:MAX_LINE]

class Blocks(HTMLParser):
    """Text per block element (li, tr, p, h*, a, td, div, option), with the first link in it."""
    BLOCK = {'li', 'tr', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'dt', 'dd', 'div', 'option', 'br', 'table'}
    CELL = {'td', 'th'}   # cells of one row stay on one line, joined by ' | ', so a posting's date stays with its title
    SKIP = {'script', 'style', 'noscript', 'head'}
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.title, self.blocks, self.buf, self.href, self.skip, self.in_title, self.text_len = base, '', [], [], None, 0, False, 0
    def flush(self):
        t = clean(' '.join(self.buf))
        if t: self.blocks.append((t, self.href))
        self.buf, self.href = [], None
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag == 'title': self.in_title = True
        if tag in self.BLOCK: self.flush()
        if tag in self.CELL and self.buf: self.buf.append('|')
        if tag == 'a' and self.href is None:
            h = dict(attrs).get('href')
            if h and not h.startswith(('javascript:', 'mailto:', '#')):
                # Wayback rewrites links in non-id_ captures; keep the original address.
                h = re.sub(r'^(https?://web\.archive\.org)?/web/\d+[a-z_]*/', '', h)
                self.href = urljoin(self.base, h)
    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag == 'title': self.in_title = False
        if tag in self.BLOCK or tag == 'a': self.flush()
    def handle_data(self, d):
        if self.in_title: self.title += d
        elif not self.skip and d.strip():
            self.buf.append(d); self.text_len += len(d.strip())

def classify(text):
    kinds = []
    if len(text) <= 200 and JOB.search(text) and not NOT_JOB.search(text) and len(text.split()) >= 2:
        kinds.append('job')
    m = MONEY.findall(text)
    if len(m) >= 2 or (m and SCHEDULE.search(text)) or len(SALARY_NUM.findall(text)) >= 3:
        kinds.append('pay')
    return kinds

def rows_from_blocks(blocks):
    out, seen = [], set()
    for text, href in blocks:
        for k in classify(text):
            key = (k, text, href)
            if key in seen: continue
            seen.add(key)
            d = DATE.search(text)
            out.append({'kind': k, 'text': text, 'date_in_text': d.group(0) if d else '', 'link': href or ''})
    return out

def text_lines_to_rows(text):
    return rows_from_blocks([(clean(l), None) for l in text.splitlines() if l.strip()])

def from_pdf(body):
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(body); f.flush()
        r = subprocess.run(['pdftotext', '-layout', '-q', f.name, '-'], capture_output=True, timeout=120)
    return r.stdout.decode('utf-8', 'replace')

def from_docx(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        x = z.read('word/document.xml').decode('utf-8', 'replace')
    x = re.sub(r'</w:p>', '\n', x)
    return re.sub(r'<[^>]+>', '', x)

def from_feed(body, url):
    root = ET.fromstring(body)
    blocks = []
    for item in root.iter():
        tag = item.tag.split('}')[-1]
        if tag not in ('item', 'entry'): continue
        title = date = link = ''
        for c in item:
            ct = c.tag.split('}')[-1]
            if ct == 'title': title = c.text or ''
            elif ct in ('pubDate', 'published', 'updated', 'date'): date = c.text or ''
            elif ct == 'link': link = c.text or c.attrib.get('href', '')
        if title: blocks.append((clean(f'{title} {date}'), urljoin(url, link.strip()) if link else None))
    return blocks

def extract(body, mimetype, url):
    info = {'title': '', 'text_chars': 0, 'job_lines': 0, 'pay_lines': 0, 'note': ''}
    lines = []
    mt = (mimetype or '').lower()
    try:
        if 'pdf' in mt or body[:5] == b'%PDF-':
            t = from_pdf(body); info['text_chars'] = len(t); lines = text_lines_to_rows(t)
        elif 'wordprocessingml' in mt or url.lower().endswith('.docx'):
            t = from_docx(body); info['text_chars'] = len(t); lines = text_lines_to_rows(t)
        elif ('rss' in mt or 'atom' in mt or re.match(rb'\s*(<\?xml[^>]*>\s*)?<(rss|feed)\b', body[:500])) and b'<html' not in body[:2000].lower():
            blocks = from_feed(body, url); info['text_chars'] = sum(len(b[0]) for b in blocks); lines = rows_from_blocks(blocks)
        elif 'html' in mt or b'<html' in body[:2000].lower():
            p = Blocks(url); p.feed(body.decode('utf-8', 'replace')); p.close(); p.flush()
            info['title'] = clean(p.title); info['text_chars'] = p.text_len; lines = rows_from_blocks(p.blocks)
        else:
            info['note'] = 'format not extracted'
    except Exception as e:
        info['note'] = f'extract error: {type(e).__name__}: {str(e)[:100]}'
    info['job_lines'] = sum(l['kind'] == 'job' for l in lines)
    info['pay_lines'] = sum(l['kind'] == 'pay' for l in lines)
    return info, lines
