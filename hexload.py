"""HexLoad / HexUpload player extractor.

Based on ResolveURL plugin by shellc0de (GPL-3.0).
Rewritten for async aiohttp.
"""
import re
import json
import base64
import logging
import aiohttp
from urllib.parse import quote

from app.utils.common_utils import get_random_agent

# Domains handled by this player
DOMAINS = ['hexload.com', 'hexupload.net']
NAMES = ['hexload', 'hexupload']

ENABLED = True

_ID_PATTERN = re.compile(r'(?://|\.)(hex(?:up)?load\.(?:net|com))/(?:embed-)?([0-9a-zA-Z]+)')


def _b64(value: str) -> str:
    return base64.b64decode(value + '=' * (-len(value) % 4)).decode('utf-8', 'ignore')


def _hidden_inputs(html: str) -> dict:
    fields = {}
    for tag in re.findall(r'<input[^>]*type=["\']hidden["\'][^>]*>', html, re.I):
        name = re.search(r'name=["\']([^"\']+)', tag)
        value = re.search(r'value=["\']([^"\']*)', tag)
        if name:
            fields[name.group(1)] = value.group(1) if value else ''
    return fields


def _quality(html: str, fields: dict) -> str:
    text = fields.get('fname', '') + ' ' + (re.search(r'<title>(.*?)</title>', html, re.S) or [None, ''])[1]
    match = re.search(r'(?<!\d)(360|480|720|1080|1440|2160)[pP](?![a-zA-Z0-9])', text)
    return f'{match.group(1)}p' if match else 'unknown'


async def get_video_from_hexload_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract direct MP4 URL from HexLoad/HexUpload."""
    try:
        match = _ID_PATTERN.search(url)
        if not match:
            logging.warning("[HexLoad] Could not extract media ID")
            return None, None, None

        media_id = match.group(2)
        page_url = f'https://{match.group(1)}/{media_id}'
        headers = {'User-Agent': get_random_agent(), 'Referer': page_url}

        async with session.get(page_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
            response.raise_for_status()
            html = await response.text()
            # hexupload.net redirects to hexload.com, the form must be posted there
            web_url = str(response.url)

        origin = web_url.rsplit('/', 1)[0]
        headers = {'User-Agent': headers['User-Agent'], 'Referer': web_url, 'Origin': origin}
        stream_headers = {'request': {'User-Agent': headers['User-Agent'], 'Referer': web_url}}

        fields = _hidden_inputs(html)
        quality = _quality(html, fields)

        # Some mp4 embeds expose the link directly
        direct = re.search(r'b4aa\.buy\("([^"]+)', html)
        if direct:
            return _b64(direct.group(1)), quality, stream_headers

        if not fields.get('id'):
            logging.warning("[HexLoad] File not found or removed")
            return None, None, None

        # Free download form: the response contains the base64 link in ldl.ld('...')
        form = {'op': 'download2', 'id': media_id, 'rand': '', 'referer': web_url, 'method_free': 'Free Download'}
        async with session.post(web_url, data=form, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
            html2 = await response.text()
        link = re.search(r"ldl\.ld\('([^']+)", html2)
        if link:
            return quote(_b64(link.group(1)), ':/?=&'), quality, stream_headers

        # Fallback: ajax variant of the first form returns {"link": base64}
        fields.update({'dataType': 'json', 'ajax': '1'})
        async with session.post(origin, data=fields, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
            body = await response.text()
            is_html = 'text/html' in response.headers.get('Content-Type', '')
        if not is_html:
            encoded = json.loads(body).get('link')
            if encoded:
                return _b64(encoded).replace(' ', '%20'), quality, stream_headers

        logging.warning("[HexLoad] No video source found")
        return None, None, None

    except Exception as e:
        logging.warning(f"[HexLoad] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://hexload.com/embed-pm6qd9jqe772/[Anime_Kage]_Elfen_Lied_-_01.mp4",
    ]

    run_tests(get_video_from_hexload_player, urls_to_test)
