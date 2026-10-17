import re
import logging
import json
import asyncio
from async_tls_client import AsyncSession
from app.utils.common_utils import get_random_agent

# Domains handled by this player
DOMAINS = ['dailymotion.com', 'dai.ly', 'geo.dailymotion.com']
NAMES = ['dailymotion']

# Headers required by Dailymotion CDN
_DM_HEADERS = {
    'Origin': 'https://www.dailymotion.com',
    'Referer': 'https://www.dailymotion.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}


async def get_video_from_dailymotion_player(session, url: str, is_vip: bool = False) -> tuple:
    """Extract video URL from Dailymotion player.

    Dailymotion requires a browser-like TLS fingerprint (aiohttp gets 403).
    Uses async-tls-client with Chrome fingerprint for extraction.
    Master manifests are IP+cookie-bound, but sub-playlists on vod CDN
    (vod*.cf.dmcdn.net) are NOT IP-bound — returned directly, no proxy needed.
    """
    try:
        pattern = r'(?://|\.)(dailymotion\.com|dai\.ly)(?:/(?:video|embed|sequence|swf|player)' \
                  r'(?:/video|/full)?)?/(?:[a-z0-9]+\.html\?video=)?(?!playlist)([0-9a-zA-Z]+)'
        match = re.search(pattern, url)
        if not match:
            return None, None, None

        media_id = match.group(2)
        user_agent = get_random_agent()
        headers = {'User-Agent': user_agent, **_DM_HEADERS}

        async with AsyncSession(
            client_identifier="chrome_120",
            random_tls_extension_order=True,
        ) as client:
            # Warm-up (cookies needed for manifest)
            await client.get('https://www.dailymotion.com/', headers=headers)

            # Get metadata
            resp = await client.get(
                f'https://www.dailymotion.com/player/metadata/video/{media_id}',
                headers=headers
            )
            if resp.status_code != 200:
                return None, None, None

            js_result = json.loads(resp.text)

            if js_result.get('error'):
                return None, None, None

            quals = js_result.get('qualities')
            if not quals:
                return None, None, None

            # Get HLS master manifest URL
            auto_qual = quals.get('auto', [])
            master_url = auto_qual[0].get('url') if auto_qual else None
            if not master_url:
                return None, None, None

            # Fetch manifest (needs cookies + TLS fingerprint)
            resp = await client.get(master_url, headers=headers)
            if resp.status_code != 200:
                logging.warning(f"[Dailymotion] Manifest fetch status {resp.status_code}")
                return None, None, None

            manifest = resp.text

        # Parse sub-playlists — vod CDN URLs are NOT IP-bound
        streams = re.findall(
            r'RESOLUTION=\d+x(\d+),NAME="(\d+)".*?\n(https?://[^\s#]+)',
            manifest
        )
        if not streams:
            return None, None, None

        # Sort by resolution, pick highest
        streams.sort(key=lambda s: int(s[0]))
        best_res, best_name, best_url = streams[-1]

        # Sub-playlists work from any IP without headers
        return best_url, f'{best_name}p', None

    except Exception as e:
        logging.warning(f"[Dailymotion] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://geo.dailymotion.com/player.html?video=k6tQ0LcFfP2BGfzcAtc"
    ]

    run_tests(get_video_from_dailymotion_player, urls_to_test)
