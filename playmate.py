import re
import logging
import aiohttp
from urllib.parse import urlparse
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

DOMAINS = ['playmate.to']
NAMES = ['playmate']

ENABLED = True


async def get_video_from_playmate_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    try:
        # Extract filecode from URL path
        match = re.search(r'/embed/([a-zA-Z0-9]+)', url)
        if not match:
            logging.warning("[Playmate] Invalid URL format - could not extract filecode")
            return None, None, None

        filecode = match.group(1)
        parsed = urlparse(url)
        host = parsed.netloc or 'playmate.to'

        user_agent = get_random_agent()
        headers = {
            "User-Agent": user_agent,
            "Content-Type": "application/json",
            "Referer": f"https://{host}/embed/{filecode}",
            "Origin": f"https://{host}",
        }

        # Call the API to get streaming URL
        api_url = f"https://{host}/api/s"
        payload = {"c": filecode, "d": "desktop"}

        async with session.post(api_url, json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=8)) as response:
            response.raise_for_status()
            data = await response.json()

        # Response fields: sx=stream_url, tx=title, ix=thumbnail, lx=language, kx=subtitles
        stream_url = data.get('sx')
        if not stream_url:
            logging.warning("[Playmate] No streaming URL in API response")
            return None, None, None

        stream_headers = {
            'request': {
                "User-Agent": user_agent,
                "Referer": f"https://{host}/",
                "Origin": f"https://{host}",
            }
        }

        try:
            quality = await fetch_resolution_from_m3u8(
                session, stream_url, stream_headers['request'], timeout=4
            ) or "unknown"
        except Exception:
            quality = "unknown"

        return stream_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[Playmate] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://playmate.to/embed/wHTxJcJbDiIum",
    ]

    run_tests(get_video_from_playmate_player, urls_to_test)
