import re
import logging
import aiohttp
from urllib.parse import urljoin

from app.utils.common_utils import get_random_agent

# Domains handled by this player
DOMAINS = ['yourupload.com', 'yucache.net']
NAMES = ['yourupload']

ENABLED = True


async def get_video_from_yourupload_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    """Extract video URL from YourUpload player"""

    try:
        # Normalize URL to embed format
        video_id_match = re.search(r'(?:yourupload\.com|yucache\.net)/(?:watch/|embed/)?([0-9A-Za-z]+)', player_url)
        if not video_id_match:
            return None, None, None

        embed_url = f"https://www.yourupload.com/embed/{video_id_match.group(1)}"

        # Referer is required by both vidcache.net hosts, not only by the embed page
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": embed_url
        }

        async with session.get(embed_url, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as response:
            response.raise_for_status()
            html_content = await response.text()

        file_match = re.search(r'''file\s*:\s*['"]([^'"]+)['"]''', html_content)
        if not file_match:
            logging.warning("[YourUpload] No video")
            return None, None, None

        # Files removed from the backend point to a placeholder clip (Big Buck Bunny)
        if 'novideo.mp4' in file_match.group(1):
            logging.warning("[YourUpload] File missing from backend")
            return None, None, None

        file_url = urljoin(embed_url, file_match.group(1))

        async with session.get(file_url, headers=headers, allow_redirects=False,
                               timeout=aiohttp.ClientTimeout(total=3)) as response:
            stream_url = response.headers.get('Location')

        if not stream_url:
            logging.warning("[YourUpload] No redirect to stream")
            return None, None, None

        quality = "unknown"
        title_match = re.search(r'<title>(.*?)</title>', html_content, re.S)
        if title_match:
            height_match = re.search(r'(?<!\d)(360|480|720|1080|1440|2160)[pP](?![a-zA-Z0-9])', title_match.group(1))
            if height_match:
                quality = f"{height_match.group(1)}p"

        stream_headers = {'request': headers}

        return stream_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[YourUpload] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://www.yourupload.com/embed/0iGkj3xhb4CD",
        "https://www.yourupload.com/watch/0iGkj3xhb4CD",
        "https://www.yourupload.com/embed/5R54J58uj032",
        "https://www.yourupload.com/embed/KmOW1idYG66m",
    ]

    run_tests(get_video_from_yourupload_player, urls_to_test)
