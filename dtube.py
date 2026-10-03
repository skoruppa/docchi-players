import re
import logging
import aiohttp
from app.utils.common_utils import get_random_agent

DOMAINS = ['d.tube', 'play.d.tube']
NAMES = ['dtube', 'd.tube']

_NAS_HOSTS = ['nas1.d.tube', 'nas2.d.tube']


async def get_video_from_dtube_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    try:
        match = re.search(
            r'(?://|\.)(d\.tube|play\.d\.tube)(?:/watch/|/embed/|/?\?v=)([0-9a-zA-Z_-]+(?:-[0-9a-zA-Z_-]+)*)',
            url
        )
        if not match:
            logging.warning("[DTube] Could not extract media ID")
            return None, None, None

        media_id = match.group(2)
        user_agent = get_random_agent()
        headers = {
            'User-Agent': user_agent,
            'Referer': 'https://play.d.tube/',
            'Origin': 'https://play.d.tube',
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

        # API sometimes returns wrong NAS - try alternatives
        stream_url = await _resolve_nas_url(session, stream_url, headers)
        if not stream_url:
            logging.warning("[DTube] Video not found on any NAS")
            return None, None, None

        quality = 'unknown'
        if data.get('height'):
            quality = f"{data['height']}p"

        stream_headers = {
            'request': {
                'User-Agent': user_agent,
                'Referer': 'https://play.d.tube/',
                'Origin': 'https://play.d.tube',
            }
        }

        return stream_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[DTube] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


async def _resolve_nas_url(session: aiohttp.ClientSession, api_url: str, headers: dict) -> str | None:
    try:
        async with session.head(api_url, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=3),
                                allow_redirects=True) as resp:
            if resp.status == 200:
                return api_url
    except Exception:
        pass

    path_match = re.search(r'https?://[^/]+(/.*)', api_url)
    if not path_match:
        return None
    path = path_match.group(1)

    for nas_host in _NAS_HOSTS:
        alt_url = f'https://{nas_host}{path}'
        if alt_url == api_url:
            continue
        try:
            async with session.head(alt_url, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=3),
                                    allow_redirects=True) as resp:
                if resp.status == 200:
                    return alt_url
        except Exception:
            continue

    return None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://play.d.tube/?v=97821eb1-1c93-457c-b793-7c68cfa03a67",
    ]

    run_tests(get_video_from_dtube_player, urls_to_test)
