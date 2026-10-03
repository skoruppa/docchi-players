import re
import logging
import aiohttp
from app.utils.common_utils import get_random_agent

# Domains handled by this player
DOMAINS = ['nanasubs.com.pl', 'vod.andawarudo.nexus']
NAMES = ['nanasubs', 'nana']


async def get_video_from_nanasubs_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from NanaSubs episode page.

    NanaSubs embeds HLS stream (vod.andawarudo.nexus) with a token directly
    in an inline <script> that initializes their NanaPlayer. No API needed —
    just scrape the HTML. Token is not IP-bound, no proxy required.
    """
    try:
        user_agent = get_random_agent()
        headers = {
            'User-Agent': user_agent,
        }

        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                logging.warning(f"[NanaSubs] Page returned status {response.status}")
                return None, None, None
            html = await response.text()

        # Extract m3u8 URL from NanaPlayer config: src: 'https://vod.andawarudo.nexus/...'
        match = re.search(
            r"src:\s*'(https://vod\.andawarudo\.nexus/[^']+)'",
            html
        )
        if not match:
            logging.warning("[NanaSubs] No m3u8 URL found in page")
            return None, None, None

        stream_url = match.group(1)

        # Detect quality from m3u8 playlist
        quality = 'unknown'
        stream_headers = {
            'request': {
                'User-Agent': user_agent,
                'Origin': 'https://nanasubs.com.pl',
                'Referer': 'https://nanasubs.com.pl/',
            }
        }

        try:
            async with session.get(stream_url, headers=stream_headers['request'],
                                   timeout=aiohttp.ClientTimeout(total=3)) as m3u8_resp:
                if m3u8_resp.status == 200:
                    m3u8_text = await m3u8_resp.text()
                    res_matches = re.findall(r'RESOLUTION=\s*(\d+)x(\d+)', m3u8_text)
                    if res_matches:
                        quality = f"{max(int(h) for w, h in res_matches)}p"
        except Exception:
            pass

        return stream_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[NanaSubs] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://nanasubs.com.pl/anime/gaikotsu-kishi-sama-tadaima-isekai-e-odekakechuu-s2/odcinek-5",
    ]

    run_tests(get_video_from_nanasubs_player, urls_to_test)
