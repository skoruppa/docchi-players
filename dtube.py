import re
import logging
import aiohttp
from app.utils.common_utils import get_random_agent

# Domains handled by this player
DOMAINS = ['d.tube', 'play.d.tube']
NAMES = ['dtube', 'd.tube']


async def get_video_from_dtube_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from DTube player."""
    try:
        # Extract media_id — supports UUIDs and alphanumeric IDs
        # Patterns: /watch/ID, /embed/ID, ?v=ID
        match = re.search(
            r'(?://|\.)(d\.tube|play\.d\.tube)(?:/watch/|/embed/|/?\?v=)([0-9a-zA-Z_-]+(?:-[0-9a-zA-Z_-]+)*)',
            url
        )
        if not match:
            logging.warning("[DTube] Could not extract media ID from URL")
            return None, None, None

        media_id = match.group(2)

        user_agent = get_random_agent()
        headers = {
            'User-Agent': user_agent,
            'Referer': 'https://d.tube/',
        }

        api_url = f'https://api.d.tube/videos/{media_id}'

        async with session.get(api_url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=8)) as response:
            if response.status != 200:
                logging.warning(f"[DTube] API returned status {response.status}")
                return None, None, None
            data = await response.json()

        stream_url = data.get('video_url')
        if not stream_url:
            logging.warning("[DTube] No video_url in API response")
            return None, None, None

        # Try to detect quality from URL or metadata
        quality = 'unknown'
        quality_match = re.search(r'(\d{3,4})[pP]', stream_url)
        if quality_match:
            quality = f'{quality_match.group(1)}p'
        elif data.get('height'):
            quality = f"{data['height']}p"
        elif data.get('quality'):
            quality = str(data['quality'])

        stream_headers = {
            'request': {
                'User-Agent': user_agent,
                'Referer': 'https://d.tube/',
            }
        }

        return stream_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[DTube] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://play.d.tube/?v=97821eb1-1c93-457c-b793-7c68cfa03a67",
    ]

    run_tests(get_video_from_dtube_player, urls_to_test)
