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


async def _get_html(session, url, headers):
    """GET HTML — through proxy if PROXIFY_STREAMS, direct otherwise."""
    if PROXIFY_STREAMS:
        from app.utils.proxy_utils import proxy_get
        text, _ = await proxy_get(session, url, headers=headers)
        return text
    async with session.get(url, headers=headers, allow_redirects=True) as resp:
        return await resp.text()


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

        html = await _get_html(session, web_url, headers)
        if not html:
            return None, None, None

        headers['Referer'] = web_url

        if 'Video not found' in html:
            return None, None, None

        # Check for iframe
        match = re.search(r'<iframe\s*src="([^"]+)', html)
        if match:
            iframe_url = urljoin(web_url, match.group(1))
            html = await _get_html(session, iframe_url, headers)
        else:
            embed_url = web_url.replace('/d/', '/e/')
            html = await _get_html(session, embed_url, headers)

        if not html:
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
        pass_url = urljoin(web_url, match.group(1))

        base_url = await _get_html(session, pass_url, headers)
        if not base_url:
            return None, None, None
        base_url = base_url.strip()

        if 'cloudflarestorage.' in base_url:
            final_url = base_url
        else:
            final_url = dood_decode(base_url) + token + str(int(time.time() * 1000))

        stream_headers = {'request': {'Referer': f'https://{host}/', 'User-Agent': user_agent}}
        return final_url, quality, stream_headers

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
