"""StreamWish / StreamHG player extractor.

Host rewrite rules based on ResolveURL plugin by gujal (GPL-3.0).
Rewritten for async aiohttp.

Stream tokens are bound to the IP that fetched the player page, so with
PROXIFY_STREAMS the page is fetched through the proxy and the stream is played
through the same proxy.
"""
import re
import json
import logging
import aiohttp
from urllib.parse import urljoin

from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8
from app.utils.proxy_utils import generate_proxy_url, proxy_get
from app.players.filelions import _unpack_filelions  # same packed-JS format as VidHide
from config import Config

# Mirrors that serve the player page (embed domains only redirect via JS or are blocked)
_MAIN_MIRRORS = ['hanerix.com', 'vibuxer.com', 'audinifer.com']
_DMCA_MIRRORS = ['hgplaycdn.com', 'hglamioz.com', 'niramirus.com', 'playnixes.com', 'medixiru.com']
# Embed domains that map to the main mirrors, everything else maps to the DMCA mirrors
_MAIN_HOSTS = {'hgcloud.to', 'dhcplay.com'}

# Domains handled by this player
DOMAINS = [
    'hgcloud.to', 'dhcplay.com', 'hgbazooka.com',
    'streamwish.com', 'streamwish.to', 'jodwish.com', 'swdyu.com', 'iplayerhls.com', 'ghbrisk.com',
    'strwish.com', 'playerwish.com', 'hlswish.com', 'swishsrv.com', 'embedwish.com', 'wishonly.site',
    'cybervynx.com', 'davioad.com',
] + _MAIN_MIRRORS + _DMCA_MIRRORS
NAMES = ['streamwish']

# NOTE: Enabled only for VIP, as whole stream needs to go through proxy
ENABLED = True

PROXIFY_STREAMS = Config.PROXIFY_STREAMS

# Mirrors tried per link: a removed file fails on every mirror, so keep this low
_MAX_ATTEMPTS = 2

_URL_PATTERN = re.compile(r'https?://(?:www\.)?([^/]+)/(?:e/|f/|d/|embed-)?([0-9a-zA-Z]+)')


async def _fetch_page(session: aiohttp.ClientSession, url: str, headers: dict) -> tuple[str | None, int]:
    """Fetch the player page, through the proxy when streams are proxified."""
    if PROXIFY_STREAMS:
        return await proxy_get(session, url, headers, timeout=6)
    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as response:
        if response.status != 200:
            return None, -1
        return await response.text(), -1


def _extract_source(html: str, page_url: str) -> str | None:
    html += _unpack_filelions(html)

    links_match = re.search(r'var\s+links\s*=\s*(\{[^}]+\})', html)
    if links_match:
        try:
            links = json.loads(links_match.group(1))
        except ValueError:
            links = {}
        # hls3 points at a host that rejects direct requests
        source = links.get('hls4') or links.get('hls2')
        if source:
            return urljoin(page_url, source)

    source_match = re.search(r'''sources:\s*\[\{file:\s*["']([^"']+)''', html)
    return urljoin(page_url, source_match.group(1)) if source_match else None


async def get_video_from_streamwish_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract HLS URL from StreamWish/StreamHG via a working mirror."""
    if not is_vip and not Config.FORCE_VIP_PLAYERS:
        return None, None, None

    try:
        match = _URL_PATTERN.search(url)
        if not match:
            logging.warning("[StreamWish] Could not extract media ID")
            return None, None, None

        host, media_id = match.group(1).lower(), match.group(2)
        if host in _MAIN_MIRRORS or host in _DMCA_MIRRORS:
            mirrors = [host]
        else:
            mirrors = _MAIN_MIRRORS if host in _MAIN_HOSTS else _DMCA_MIRRORS

        user_agent = get_random_agent()
        for mirror in mirrors[:_MAX_ATTEMPTS]:
            page_url = f'https://{mirror}/e/{media_id}'
            headers = {'User-Agent': user_agent, 'Referer': f'https://{mirror}/'}

            html, proxy_idx = await _fetch_page(session, page_url, headers)
            stream_url = _extract_source(html, page_url) if html else None
            if not stream_url:
                continue

            stream_headers = {**headers, 'Origin': f'https://{mirror}'}
            try:
                quality = await fetch_resolution_from_m3u8(
                    session, stream_url, stream_headers, use_proxy=PROXIFY_STREAMS
                )
            except Exception:
                quality = None

            # Play through the proxy that fetched the page (proxy_idx is -1 when it fell back to direct)
            if PROXIFY_STREAMS and proxy_idx >= 0:
                stream_url = await generate_proxy_url(
                    session, stream_url, '/proxy/hls/manifest.m3u8',
                    request_headers=stream_headers,
                    proxy_index=proxy_idx,
                )
                return stream_url, quality or 'unknown', None

            return stream_url, quality or 'unknown', {'request': stream_headers}

        logging.warning(f"[StreamWish] No video source found for {host}/{media_id} (file removed?)")
        return None, None, None

    except Exception as e:
        logging.warning(f"[StreamWish] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://hgcloud.to/e/6x18isk8m8sx",
        "https://ghbrisk.com/e/x8biutbak1dy",
    ]

    run_tests(get_video_from_streamwish_player, urls_to_test, is_vip=True)
