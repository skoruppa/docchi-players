import re
import logging
import aiohttp
from aiohttp.client_exceptions import ClientConnectorError, ClientResponseError
import json
import urllib.parse
from app.utils.proxy_utils import generate_proxy_url
from config import Config

# Domains handled by this player
DOMAINS = ['m.cda.pl', 'cda.pl', 'www.cda.pl', 'ebd.cda.pl']
NAMES = ['cda']

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


def decrypt_url(url: str) -> str:
    for p in ("_XDDD", "_CDA", "_ADC", "_CXD", "_QWE", "_Q5", "_IKSDE"):
        url = url.replace(p, "")
    url = urllib.parse.unquote(url)
    b = []
    for c in url:
        f = c if isinstance(c, int) else ord(c)
        b.append(chr(33 + (f + 14) % 94) if 33 <= f <= 126 else chr(f))
    a = "".join(b)
    a = a.replace(".cda.mp4", "")
    a = a.replace(".2cda.pl", ".cda.pl")
    a = a.replace(".3cda.pl", ".cda.pl")
    if "/upstream" in a:
        a = a.replace("/upstream", ".mp4/upstream")
        return "https://" + a
    return "https://" + a + ".mp4"


def normalize_cda_url(url):
    pattern = r"https?://(?:www\.|m\.)?cda\.pl/(?:video/)?([\w]+)(?:\?.*)?|https?://ebd\.cda\.pl/\d+x\d+/([\w]+)"
    match = re.match(pattern, url)
    if match:
        video_id = match.group(1) or match.group(2)
        return f"https://www.cda.pl/video/{video_id}", video_id
    return None, None


def get_highest_quality(qualities: dict) -> tuple:
    qualities.pop('auto', None)
    highest_quality = max(qualities.keys(), key=lambda x: int(x.rstrip('p')))
    return highest_quality, qualities[highest_quality]


async def _proxy_get_html(session: aiohttp.ClientSession, url: str) -> str | None:
    """GET request through proxy and return HTML text."""
    if PROXIFY_STREAMS:
        forward_url = (
            f'{STREAM_PROXY_URL}/proxy/stream?d={url}'
            f'&api_password={STREAM_PROXY_PASSWORD}'
            f'&h_user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        async with session.get(forward_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            return await resp.text()
    else:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.text()


async def _proxy_post_html(session: aiohttp.ClientSession, url: str, form_data: dict) -> str | None:
    """POST form data through proxy and return HTML text."""
    if PROXIFY_STREAMS:
        forward_url = (
            f'{STREAM_PROXY_URL}/proxy/forward?d={url}'
            f'&api_password={STREAM_PROXY_PASSWORD}'
            f'&h_user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            f'&h_content-type=application/x-www-form-urlencoded'
        )
        body = urllib.parse.urlencode(form_data)
        async with session.post(forward_url, data=body,
                                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            return await resp.text()
    else:
        data = aiohttp.FormData()
        for k, v in form_data.items():
            data.add_field(k, v)
        async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.text()


def _parse_player_data(html: str) -> dict | None:
    """Extract player_data JSON from CDA HTML."""
    match = re.search(r"player_data='(.*?)'\s+tabindex", html, re.DOTALL)
    if not match:
        match = re.search(r'player_data=[\'"]([^\'"]+)[\'"]', html)
    if not match:
        return None
    try:
        raw = match.group(1).replace('&quot;', '"').replace('&#39;', "'")
        return json.loads(raw)
    except Exception:
        return None


async def get_video_from_cda_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False) -> tuple:
    """Extract video URL from CDA player.
    
    CDA is IP-bound — extraction goes through proxy so the resulting URL
    is bound to the proxy's IP (which also serves the stream to the user).
    """
    url, video_id = normalize_cda_url(url)
    if not url:
        return None, None, None

    try:
        # Step 1: Fetch page (through proxy if available)
        html = await _proxy_get_html(session, url)
        if not html:
            return None, None, None

        # Handle age confirmation
        if 'age_confirm' in html:
            html = await _proxy_post_html(session, url, {'age_confirm': ''})
            if not html:
                return None, None, None

        video_data = _parse_player_data(html)
        if not video_data:
            return None, None, None

        qualities = video_data['video']['qualities']
        file = video_data['video'].get('file', '')
        highest_quality, quality_id = get_highest_quality(qualities)

        # Step 2: Re-fetch with highest quality if needed
        if not file or video_data['video'].get('quality') != quality_id:
            hq_url = f'{url}?wersja={highest_quality}'
            html = await _proxy_get_html(session, hq_url)
            if html:
                video_data = _parse_player_data(html)
                if video_data:
                    file = video_data['video'].get('file', '')

        # Step 3: Build video URL
        if file:
            video_url = decrypt_url(file)
        else:
            video_url = video_data['video'].get('manifest_apple', '')

        if not video_url:
            return None, None, None

        referer = f"https://ebd.cda.pl/620x368/{video_id}"

        # Step 4: Proxy the stream URL (IP-bound)
        if PROXIFY_STREAMS:
            is_hls = video_url.endswith('.m3u8') or '/manifest' in video_url
            proxy_endpoint = '/proxy/hls/manifest.m3u8' if is_hls else '/proxy/stream'
            video_url = await generate_proxy_url(
                session, video_url, proxy_endpoint,
                request_headers={"Referer": referer}
            )
            return video_url, highest_quality, None

        return video_url, highest_quality, {"request": {"Referer": referer}}

    except Exception as e:
        logging.warning(f"[CDA] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://ebd.cda.pl/1055x594/27664708b6"
    ]

    run_tests(get_video_from_cda_player, urls_to_test)
