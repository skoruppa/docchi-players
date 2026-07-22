import logging
import aiohttp
from urllib.parse import urljoin, urlparse
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['flyfile.app']
NAMES = ['flyfile']

ENABLED = True


async def get_video_from_flyfile_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from FlyFile player via streaming assign API."""
    try:
        import re
        match = re.search(r'/embed/([A-Za-z0-9]+)', url)
        if not match:
            logging.warning("[FlyFile] Invalid URL format")
            return None, None, None

        media_id = match.group(1)
        parsed = urlparse(url)
        host = parsed.netloc

        user_agent = get_random_agent()
        headers = {
            "User-Agent": user_agent,
            "Referer": url,
            "Origin": f"https://{host}",
        }

        assign_url = f"https://api.{host}/api/streaming/assign/{media_id}"

        async with session.get(assign_url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            data = await response.json()

        stream_base = data.get('url')
        token = data.get('token')

        if not stream_base or not token:
            logging.warning("[FlyFile] Missing url or token in response")
            return None, None, None

        stream_url = f"{stream_base.rstrip('/')}/hls/{token}/master.m3u8"

        stream_headers = {
            'request': headers
        }

        try:
            quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
        except Exception:
            quality = "unknown"

        return stream_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[FlyFile] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://flyfile.app/embed/gKJR4DrMgGEbeHl",
    ]

    run_tests(get_video_from_flyfile_player, urls_to_test)
