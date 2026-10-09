"""GameCopyWorld catalogue lookup and bounded archive downloads."""
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlparse, parse_qs
import urllib.request
import uuid
import http.cookiejar
import threading

BASE = 'https://gamecopyworld.eu/games/'
SESSION = threading.local()


def normalized(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKD', value).casefold()))


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.active = None
    def handle_starttag(self, tag, attrs):
        if tag == 'a': self.active = [dict(attrs).get('href', ''), '']
    def handle_data(self, data):
        if self.active: self.active[1] += data
    def handle_endtag(self, tag):
        if tag == 'a' and self.active:
            self.links.append(tuple(self.active)); self.active = None


def allowed(url):
    host = urlparse(url).hostname or ''
    return urlparse(url).scheme == 'https' and (any(host == domain or host.endswith('.' + domain) for domain in ('gamecopyworld.eu', 'gamecopyworld.com')) or bool(re.fullmatch(r'g[0-9]{2}\.mobiletarget\.net', host)) or host in {'d1.consoletarget.com', 'd2.consoletarget.com', 'd3.consoletarget.com', 'd4.consoletarget.com'})


def fetch(url):
    if not allowed(url): raise ValueError('Unsupported GameCopyWorld link.')
    if not hasattr(SESSION, 'opener'):
        SESSION.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    response = SESSION.opener.open(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': BASE}), timeout=25)
    if not allowed(response.url):
        response.close(); raise ValueError('Mirror requires a browser.')
    return response


def html(url):
    with fetch(url) as response:
        data = response.read(8 * 1024**2 + 1)
        if len(data) > 8 * 1024**2: raise ValueError('Catalogue page exceeded size limit.')
        return data.decode('utf-8', errors='replace')


def search(name):
    query = normalized(name)
    if not query: return []
    first = query[0]
    index = 'gcw_index.shtml' if first < 'f' else 'gcw_index_2.shtml' if first < 'n' else 'gcw_index_3.shtml' if first < 't' else 'gcw_index_4.shtml'
    parser = Links(); parser.feed(html(BASE + index))
    results = []
    for href, title in parser.links:
        if re.fullmatch(r'pc_[^/]+\.shtml', href) and query in normalized(title):
            results.append(dict(title=title.strip(), url=urljoin(BASE, href)))
    return results[:100]


def patches(url):
    page = html(url)
    results = []
    sections = list(re.finditer(r'<a\s+name=[\"\']([^\"\']+)', page, re.I))
    for match in re.finditer(r"cbox\(\s*['\"](https://dl\.gamecopyworld\.(?:eu|com)/[^'\"]+)", page):
        section = next((unescape(entry.group(1)) for entry in reversed(sections) if entry.start() < match.start()), '')
        if not re.search(r'\bfixed\s+(?:files?|exe(?:cutables?)?)\b', section, re.I) or re.search(r'trainer|unlocker', section, re.I):
            continue
        link = unescape(match.group(1))
        filename = parse_qs(urlparse(link).query).get('f', [''])[0]
        if not filename or re.search(r'trainer|unlocker', filename, re.I): continue
        title = filename.replace('!', '.')
        results.append(dict(title=title, url=link))
    return results


def download(url, downloads):
    """Download an archive or fail to a browser; never treat HTML as a file."""
    filename = parse_qs(urlparse(url).query).get('f', [''])[0].replace('!', '.')
    filename = re.sub(r'[\\/\x00-\x1f<>:"|?*]', '', filename).strip(' .')[:180]
    pending, seen = [url], set()
    for _ in range(12):
        if not pending: break
        url = pending.pop(0)
        if url in seen: continue
        seen.add(url)
        try:
            response = fetch(url)
        except (OSError, ValueError):
            continue
        with response:
            prefix = response.read(8)
            extension = '.zip' if prefix.startswith(b'PK') else '.7z' if prefix.startswith(b'7z\xbc\xaf\x27\x1c') else '.rar' if prefix.startswith(b'Rar!') else None
            if extension:
                downloads = Path(downloads); downloads.mkdir(parents=True, exist_ok=True)
                name = filename if filename.lower().endswith(extension) else 'GameCopyWorld-' + uuid.uuid4().hex[:12] + extension
                target = downloads / name
                if target.exists() or target.with_suffix(extension + '.partial').exists():
                    target = downloads / (Path(name).stem + '-' + uuid.uuid4().hex[:8] + extension)
                partial = target.with_suffix(extension + '.partial')
                try:
                    with partial.open('xb') as output:
                        output.write(prefix); size = len(prefix)
                        while chunk := response.read(1024 * 1024):
                            size += len(chunk)
                            if size > 2 * 1024**3: raise ValueError('Download exceeds 2 GiB.')
                            output.write(chunk)
                    partial.rename(target)
                finally:
                    partial.unlink(missing_ok=True)
                return str(target)
            data = prefix + response.read(2 * 1024**2)
            parser = Links(); parser.feed(data.decode(errors='replace'))
            candidates = [urljoin(response.url, href) for href, _ in parser.links
                          if (re.search(r'\.(zip|rar|7z)(?:\?|$)', href, re.I) or re.fullmatch(r'MIRROR\s*#?\d+', _.strip().strip('[] '), re.I))
                          and allowed(urljoin(response.url, href))]
            pending.extend(link for link in candidates if link not in seen)
    raise ValueError('This mirror requires a browser download. Choose the downloaded archive afterward.')
