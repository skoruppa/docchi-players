import re
import time
import string
import random
from urllib.parse import urlparse, urljoin
from async_tls_client import AsyncSession

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


def dood_decode(data):
    t = string.ascii_letters + string.digits
    return data + ''.join([random.choice(t) for _ in range(10)])


def _random_ua():
    """Generate a random Chrome User-Agent string"""
    version = random.randint(120, 130)
    build = random.randint(6000, 6900)
    patch = random.randint(50, 200)
    return f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.{build}.{patch} Safari/537.36'


async def get_video_from_dood_player(session, player_url, is_vip: bool = False):
    """Extract video URL from DoodStream player"""
    from app.utils.common_utils import fetch_resolution_from_m3u8

    parsed = urlparse(player_url)
    host = parsed.hostname
    video_id = parsed.path.rstrip('/').split('/')[-1]

    if host not in ['doodstream.com', 'myvidplay.com', 'playmogo.com']:
        host = 'playmogo.com'

    web_url = f"https://{host}/d/{video_id}"
    user_agent = _random_ua()

    try:
        async with AsyncSession(client_identifier="chrome_131", random_tls_extension_order=True) as client:
            headers = {
                'User-Agent': user_agent,
                'Referer': f'https://{host}/'
            }

            response = await client.get(web_url, headers=headers, allow_redirects=True)
            actual_url = str(response.url) if hasattr(response, 'url') else web_url

            if actual_url != web_url:
                host_match = re.findall(r'(?://|\.)([^/]+)', actual_url)
                if host_match:
                    host = host_match[0]
                    web_url = f"https://{host}/d/{video_id}"

            headers['Referer'] = web_url
            html = response.text

            if 'Video not found' in html:
                return None, None, None

            # Check for iframe
            match = re.search(r'<iframe\s*src="([^"]+)', html)
            if match:
                iframe_url = urljoin(web_url, match.group(1))
                response = await client.get(iframe_url, headers=headers, allow_redirects=True)
                html = response.text
            else:
                embed_url = web_url.replace('/d/', '/e/')
                response = await client.get(embed_url, headers=headers, allow_redirects=True)
                html = response.text

            # Try to extract quality from page HTML
            quality = 'unknown'
            quality_match = re.search(r'(\d{3,4})[pP]', html)
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

            response = await client.get(pass_url, headers=headers, allow_redirects=True)
            base_url = response.text.strip()

            if 'cloudflarestorage.' in base_url:
                final_url = base_url
            else:
                final_url = dood_decode(base_url) + token + str(int(time.time() * 1000))

            stream_headers = {'request': {'Referer': f'https://{host}/', 'User-Agent': user_agent}}
            return final_url, quality, stream_headers

    except Exception:
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://myvidplay.com/e/l1ebnruggzly",
        "https://playmogo.com/e/8fxz57u9cfis",
        "https://dood.yt/e/aorzlvboafi6"
    ]

    run_tests(get_video_from_dood_player, urls_to_test)
