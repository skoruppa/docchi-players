import re
import logging
import aiohttp
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['dailymotion.com', 'dai.ly']
NAMES = ['dailymotion']

# Headers required by Dailymotion CDN (CORS + Sec-Fetch)
_DM_HEADERS = {
    'Origin': 'https://www.dailymotion.com',
    'Referer': 'https://www.dailymotion.com/',
}


async def get_video_from_dailymotion_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False) -> tuple:
    try:
        # Extract media_id from URL
        pattern = r'(?://|\.)(dailymotion\.com|dai\.ly)(?:/(?:video|embed|sequence|swf|player)' \
                  r'(?:/video|/full)?)?/(?:[a-z0-9]+\.html\?video=)?(?!playlist)([0-9a-zA-Z]+)'
        match = re.search(pattern, url)
        if not match:
            return None, None, None

        media_id = match.group(2)
        user_agent = get_random_agent()

        headers = {
            'User-Agent': user_agent,
            **_DM_HEADERS,
        }

        # Sec-Fetch headers needed to fetch HLS manifest from CDN
        fetch_headers = {
            **headers,
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
        }

        # Warm-up session to get cookies (dmvk etc.)
        async with session.get('https://www.dailymotion.com/', headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
            pass

        # Get metadata
        metadata_url = f'https://www.dailymotion.com/player/metadata/video/{media_id}'
        async with session.get(metadata_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
            response.raise_for_status()
            js_result = await response.json()

        if js_result.get('error'):
            return None, None, None

        quals = js_result.get('qualities')
        if not quals:
            return None, None, None

        video_headers = {"request": {"User-Agent": user_agent, **_DM_HEADERS}}

        # Priority 1: Direct MP4 (if available)
        for q in ['1080', '720', '480', '380', '240']:
            if q in quals:
                for source in quals[q]:
                    if source.get('type') == 'video/mp4':
                        mp4_url = source.get('url')
                        if mp4_url:
                            return mp4_url, f'{q}p', video_headers

        # Priority 2: HLS — fetch manifest, extract best sub-playlist
        auto_qual = quals.get('auto', [])
        if auto_qual:
            master_url = auto_qual[0].get('url')
            if master_url:
                try:
                    async with session.get(master_url, headers=fetch_headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            manifest = await resp.text()
                            # Parse NAME and sub-playlist URL pairs
                            streams = re.findall(
                                r'RESOLUTION=\d+x(\d+),NAME="(\d+)".*?\n(https?://[^\s]+)',
                                manifest
                            )
                            if streams:
                                # Sort by resolution, pick highest
                                streams.sort(key=lambda s: int(s[0]))
                                best_res, best_name, best_url = streams[-1]
                                # Sub-playlists on vod CDN don't need special headers
                                return best_url, f'{best_name}p', None
                except Exception as e:
                    logging.warning(f"[Dailymotion] Manifest fetch failed: {e}")

                # Fallback: return master manifest URL with headers for Stremio
                quality = 'unknown'
                try:
                    quality = await fetch_resolution_from_m3u8(session, master_url, fetch_headers) or quality
                except Exception:
                    pass
                return master_url, quality, video_headers

        return None, None, None

    except Exception as e:
        logging.warning(f"[Dailymotion] {type(e).__name__}: {e or 'no details'}")
        return None, None, None

if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://www.dailymotion.com/embed/video/x7tgad0"
    ]

    run_tests(get_video_from_dailymotion_player, urls_to_test)
