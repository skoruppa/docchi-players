"""FileLions/VidHide player extractor.

Based on ResolveURL plugin by gujal (GPL-3.0).
Rewritten for async aiohttp.
"""
import re
import logging
import aiohttp
from urllib.parse import urljoin
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8
from app.utils.proxy_utils import generate_proxy_url
from app.utils.jsunpack import unpack as js_unpack
from config import Config

DOMAINS = [
    'filelions.com', 'filelions.to', 'filelions.live', 'filelions.xyz', 'filelions.online',
    'filelions.site', 'filelions.co', 'vidhide.com', 'vidhidepro.com', 'vidhidevip.com',
    'vidhideplus.com', 'vidhidepre.com', 'vidhide.fun', 'vidhidehub.com', 'vidhidefast.com',
    'moflix-stream.click', 'azipcdn.com', 'mlions.pro', 'alions.pro', 'dlions.pro',
    'lumiawatch.top', 'javplaya.com', 'fviplions.com', 'javlion.xyz',
    'techradar.ink', 'anime7u.com', 'coolciima.online', 'katomen.online',
    'dhtpre.com', 'streamvid.su', 'movearnpre.com', 'bingezove.com',
    'dingtezuni.com', 'dinisglows.com', 'ryderjet.com', 'smoothpre.com',
    'videoland.sbs', 'taylorplayer.com', 'mivalyo.com', 'peytonepre.com',
    'dintezuvio.com', 'callistanise.com', 'minochinos.com', 'earnvids.xyz',
    'lookmovie2.skin', 'morencius.com', 'kinoger.be', 'motvy55.store',
    'ajmidyadfihayh.sbs', 'alhayabambi.sbs', 'egsyxutd.sbs', 'fdewsdc.sbs',
    'gsfomqu.sbs', '6sfkrspw4u.sbs', 'e4xb5c2xnz.sbs',
]
NAMES = ['filelions', 'vidhide']

ENABLED = True

PROXIFY_STREAMS = Config.PROXIFY_STREAMS

# Dead domains redirect to this
_FALLBACK_HOST = 'callistanise.com'
_DEAD_DOMAINS = {
    'filelions.com', 'filelions.to', 'ajmidyadfihayh.sbs', 'alhayabambi.sbs', 'vidhideplus.com',
    'azipcdn.com', 'mlions.pro', 'alions.pro', 'dlions.pro', 'mivalyo.com', 'vidhidefast.com',
    'filelions.live', 'motvy55.store', 'filelions.xyz', 'lumiawatch.top', 'filelions.online',
    'fviplions.com', 'egsyxutd.sbs', 'filelions.site', 'filelions.co', 'vidhidepre.com',
    'vidhidepro.com', 'vidhidevip.com', 'e4xb5c2xnz.sbs', 'taylorplayer.com', 'ryderjet.com',
    'techradar.ink', 'anime7u.com', 'coolciima.online', 'gsfomqu.sbs', 'bingezove.com',
    'katomen.online', 'vidhide.fun', '6sfkrspw4u.sbs', 'dingtezuni.com', 'dinisglows.com',
    'dintezuvio.com',
}


def _get_packed_data(html: str) -> str:
    """Extract and unpack packed JS from HTML."""
    packed = ''
    for match in re.finditer(r"(eval\s*\(function\(p,a,c,k,e,[dr].*?\))", html, re.DOTALL):
        try:
            packed += js_unpack(match.group(1))
        except Exception:
            pass
    return packed


def _unpack_filelions(html: str) -> str:
    """Unpack FileLions-style packed JS (handles escaped quotes in payload)."""
    start = html.find("eval(function(p,a,c,k,e,d)")
    if start < 0:
        return ''

    pstart = html.find("('", start) + 2

    # Scan for unescaped ' followed by ,digits,digits,'
    i = pstart
    while i < len(html):
        if html[i] == "'" and (i == 0 or html[i - 1] != '\\'):
            m = re.match(r"',(\d+),(\d+),'", html[i:i + 20])
            if m:
                payload = html[pstart:i]
                base = int(m.group(1))
                count = int(m.group(2))

                words_start = i + len(m.group(0))
                words_end = html.find("'.split", words_start)
                words = html[words_start:words_end].split('|')

                def to_base(n, b):
                    d = '0123456789abcdefghijklmnopqrstuvwxyz'
                    return d[n] if n < b else to_base(n // b, b) + d[n % b]

                rep = {}
                for j in range(min(count, len(words))):
                    if words[j]:
                        rep[to_base(j, base)] = words[j]

                return re.sub(r'\b([0-9a-z]+)\b', lambda m: rep.get(m.group(1), m.group(1)), payload)
        i += 1
    return ''


async def get_video_from_filelions_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from FileLions/VidHide player."""
    try:
        # Extract host and media_id from URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path.lstrip('/')

        # Replace dead domains
        if host in _DEAD_DOMAINS:
            host = _FALLBACK_HOST

        web_url = f'https://{host}/{path}'
        headers = {
            'User-Agent': get_random_agent(),
            'Referer': f'https://{host}/',
        }

        async with session.get(web_url, headers=headers, ssl=False,
                               timeout=aiohttp.ClientTimeout(total=10),
                               allow_redirects=True) as resp:
            if resp.status != 200:
                logging.warning(f"[FileLions] HTTP {resp.status} for {web_url}")
                return None, None, None
            html = await resp.text()

        # Unpack any packed JS
        unpacked = _unpack_filelions(html)
        if unpacked:
            html += unpacked

        ref = f'https://{host}/'
        stream_headers = {
            'User-Agent': headers['User-Agent'],
            'Referer': ref,
            'Origin': ref.rstrip('/'),
        }

        # Method 1: var links = {...}
        links_match = re.search(r'var\s+links\s*=\s*(\{[^}]+\})', html)
        if links_match:
            import ast
            try:
                links = ast.literal_eval(links_match.group(1))
                source = links.get('hls4') or links.get('hls3') or links.get('hls2')
                if source:
                    if source.startswith('/'):
                        source = urljoin(web_url, source)
                    return await _finalize(session, source, stream_headers)
            except Exception:
                pass

        # Method 2: sources: [{file: "..."}]
        source_match = re.search(r'''sources:\s*\[\{file:\s*["']([^"']+)''', html)
        if source_match:
            source = source_match.group(1)
            return await _finalize(session, source, stream_headers)

        logging.warning("[FileLions] No video source found")
        return None, None, None

    except Exception as e:
        logging.warning(f"[FileLions] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


async def _finalize(session, stream_url, headers):
    """Return stream URL with resolved quality."""
    try:
        quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or 'unknown'
    except Exception:
        quality = 'unknown'
    return stream_url, quality, {'request': headers}


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://morencius.com/embed/838c7svroe0b",
    ]

    run_tests(get_video_from_filelions_player, urls_to_test)
