import re
import time
import string
import random
import logging
import aiohttp
from urllib.parse import urlparse, urljoin
from app.utils.common_utils import get_random_agent
from config import Config

DOMAINS = [
    'dood.watch', 'doodstream.com', 'dood.to', 'dood.so', 'dood.cx', 'dood.la', 'dood.ws',
    'dood.sh', 'doodstream.co', 'dood.pm', 'dood.wf', 'dood.re', 'dood.yt', 'dooood.com',
    'dood.stream', 'ds2play.com', 'doods.pro', 'ds2video.com', 'd0o0d.com', 'do0od.com',
    'd0000d.com', 'd000d.com', 'dood.li', 'dood.work', 'dooodster.com', 'vidply.com',
    'all3do.com', 'do7go.com', 'doodcdn.io', 'doply.net', 'vide0.net', 'vvide0.com',
    'd-s.io', 'dsvplay.com', 'myvidplay.com', 'playmogo.com'
]
NAMES = ['dood']

ENABLED = True
PROXIFY_STREAMS = Config.PROXIFY_STREAMS


async def _get_html(session, url, headers, expect_full_page=True, force_proxy_index=None):
    """GET HTML — through proxy if PROXIFY_STREAMS, direct otherwise.
    If expect_full_page=True, detects stripped dood pages and tries next proxy.
    Returns (text, proxy_index_used) tuple."""
    if PROXIFY_STREAMS:
        from app.utils.proxy_utils import _PROXIES
        ua = (headers or {}).get('User-Agent', 'Mozilla/5.0')
        referer = (headers or {}).get('Referer', '')

        start = force_proxy_index if force_proxy_index is not None else 0
        for i in range(start, len(_PROXIES)):
            proxy_url, proxy_password = _PROXIES[i]
            forward_url = (
                f'{proxy_url}/proxy/stream?d={url}'
                f'&api_password={proxy_password}'
                f'&h_user-agent={ua}'
            )
            if referer:
                forward_url += f'&h_referer={referer}'
            try:
                async with session.get(forward_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                    if expect_full_page and len(text) < 10000 and 'dsplayer' not in text and 'makePlay' not in text:
                        logging.info(f"[Dood] Proxy {i} returned stripped page ({len(text)} chars), trying next")
                        continue
                    return text, i
            except Exception:
                continue

        # All proxies failed — try direct
        try:
            async with session.get(url, headers=headers, allow_redirects=True,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return await resp.text(), -1
        except Exception:
            return None, -1
    else:
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            return await resp.text(), -1


def dood_decode(data):
    t = string.ascii_letters + string.digits
    return data + ''.join([random.choice(t) for _ in range(10)])


async def get_video_from_dood_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    """Extract video URL from DoodStream player"""

    parsed = urlparse(player_url)
    host = parsed.hostname
    video_id = parsed.path.rstrip('/').split('/')[-1]

    if host not in ['doodstream.com', 'myvidplay.com', 'playmogo.com']:
        host = 'playmogo.com'

    web_url = f"https://{host}/d/{video_id}"
    user_agent = get_random_agent()

    try:
        headers = {
            'User-Agent': user_agent,
            'Referer': f'https://{host}/'
        }

        # Go straight to embed page (has the player code)
        embed_url = f"https://{host}/e/{video_id}"
        html, working_proxy = await _get_html(session, embed_url, headers)
        if not html:
            return None, None, None

        if 'Video not found' in html:
            return None, None, None

        # Try to extract quality from page HTML
        quality = 'unknown'
        quality_match = re.search(r'\b(360|480|720|1080|1440|2160)[pP]', html)
        if quality_match:
            quality = f"{quality_match.group(1)}p"

        # Extract token and pass URL using dsplayer.hotkeys pattern
        match = re.search(
            r'''dsplayer\.hotkeys[^']+'([^']+).+?function\s*makePlay.+?return[^?]+([^"]+)''',
            html, re.DOTALL
        )
        if not match:
            return None, None, None

        token = match.group(2)
        pass_url = urljoin(embed_url, match.group(1))

        base_url, _ = await _get_html(session, pass_url, headers, expect_full_page=False, force_proxy_index=working_proxy if working_proxy >= 0 else None)
        if not base_url:
            return None, None, None
        base_url = base_url.strip()

        if 'cloudflarestorage.' in base_url:
            final_url = base_url
        else:
            final_url = dood_decode(base_url) + token + str(int(time.time() * 1000))

        stream_headers = {'Referer': f'https://{host}/', 'User-Agent': user_agent}

        # Dood is IP-bound — proxy the stream through the same proxy that extracted it
        if PROXIFY_STREAMS and working_proxy >= 0:
            from app.utils.proxy_utils import generate_proxy_url
            final_url = await generate_proxy_url(
                session, final_url, '/proxy/stream',
                request_headers=stream_headers,
                proxy_index=working_proxy,
            )
            return final_url, quality, None

        return final_url, quality, {'request': stream_headers}

    except Exception as e:
        logging.warning(f"[Dood] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://myvidplay.com/e/l1ebnruggzly",
        "https://playmogo.com/e/8fxz57u9cfis",
        "https://dood.yt/e/aorzlvboafi6"
    ]

    run_tests(get_video_from_dood_player, urls_to_test)
