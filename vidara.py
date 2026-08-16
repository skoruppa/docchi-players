import re
import logging
import aiohttp
from urllib.parse import urljoin, urlparse
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['vidara.so', 'vidara.to', 'vidaraa.cc', 'vidavaca.cc', 'thebesthosterv.com', 'vidchampions.com', 'streamix.so', 'stmix.io', 'viewdara.com', 'odysseusa.cc']
NAMES = ['vidara', 'vidavaca', 'streamix']

ENABLED = True


async def get_video_from_vidara_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from Vidara/Streamix player."""
    try:
        match = re.search(r'/(?:e|v)/([0-9a-zA-Z]+)', url)
        if not match:
            logging.warning("[Vidara] Invalid URL format")
            return None, None, None

        media_id = match.group(1)
        parsed = urlparse(url)
        host = parsed.netloc
        ref = urljoin(url, '/')

        # vidara/vidavaca uses /api/, streamix uses /ajax/
        if 'stmix' in host or 'streamix' in host:
            api_url = f"https://{host}/ajax/stream"
        else:
            api_url = f"https://{host}/api/stream"

        user_agent = get_random_agent()
        headers = {
            "User-Agent": user_agent,
            "Referer": url,
            "Origin": ref.rstrip('/'),
            "Content-Type": "application/json"
        }

        payload = {"filecode": media_id, "device": "web"}

        # NOTE: Vidara tokens are IP-bound - extraction must be direct (not proxied)
        # so the token matches the server IP for quality check and user's Stremio client
        async with session.post(api_url, json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=5)) as response:
            response.raise_for_status()
            data = await response.json()

        streaming_url = data.get('streaming_url')
        if not streaming_url:
            logging.warning("[Vidara] No streaming_url in response")
            return None, None, None

        # Stream headers for playback (direct, no proxy)
        stream_headers = {
            'request': {
                "User-Agent": user_agent,
                "Referer": url,
                "Origin": ref.rstrip('/')
            }
        }

        try:
            quality = await fetch_resolution_from_m3u8(session, streaming_url, stream_headers['request'], timeout=4) or "unknown"
        except Exception:
            quality = "unknown"

        return streaming_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[Vidara] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://vidavaca.cc/e/RzV4IEzlG1ZxG",
    ]

    run_tests(get_video_from_vidara_player, urls_to_test)
