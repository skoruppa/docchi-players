import re
import logging
import aiohttp
from urllib.parse import urlparse
from app.utils.common_utils import get_random_agent

DOMAINS = ['sendvid.com']
NAMES = ['sendvid']

ENABLED = True


async def get_video_from_sendvid_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    """Extract video URL from SendVid player"""

    parsed = urlparse(player_url)
    host = parsed.hostname
    path = parsed.path.rstrip('/')
    video_id = path.split('/')[-1]

    # Use direct page URL (not embed)
    web_url = f"https://{host}/{video_id}"
    user_agent = get_random_agent()

    try:
        headers = {
            'User-Agent': user_agent,
        }

        async with session.get(web_url, headers=headers, allow_redirects=True) as response:
            html = await response.text()

        # Pattern from ResolveURL: source src="URL"
        match = re.search(r'''source\s*src="(?P<url>[^"]+)''', html)
        if not match:
            # Fallback: try video source tag
            match = re.search(r'<source[^>]+src="([^"]+)"', html)

        if not match:
            logging.warning("[SendVid] No video source found")
            return None, None, None

        final_url = match.group(1) if match.lastindex else match.group('url')

        # Try to detect quality
        quality = 'unknown'
        quality_match = re.search(r'\b(360|480|720|1080|1440|2160)[pP]?', html)
        if quality_match:
            quality = f"{quality_match.group(1)}p"

        stream_headers = {'request': {'User-Agent': user_agent}}
        return final_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[SendVid] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://sendvid.com/embed/nzhbbd7k"
    ]

    run_tests(get_video_from_sendvid_player, urls_to_test)
