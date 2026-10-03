import re
import json
import logging
import aiohttp
from app.utils.common_utils import get_random_agent

DOMAINS = ['nanasubs.com.pl']
NAMES = ['nanasubs', 'nana']


async def get_video_from_nanasubs_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    try:
        user_agent = get_random_agent()
        headers = {'User-Agent': user_agent}

        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                logging.warning(f"[NanaSubs] Page returned status {response.status}")
                return None, None, None
            html = await response.text()

        match = re.search(r"src:\s*'(https?://[^']+\.m3u8[^']*)'", html)
        if not match:
            logging.warning("[NanaSubs] No m3u8 URL found")
            return None, None, None

        stream_url = match.group(1)
        subtitles = _extract_subtitles(html)

        quality = 'unknown'
        stream_headers = {
            'request': {
                'User-Agent': user_agent,
                'Origin': 'https://nanasubs.com.pl',
                'Referer': 'https://nanasubs.com.pl/',
            }
        }

        if subtitles:
            stream_headers['subtitles'] = subtitles

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


def _extract_subtitles(html: str) -> list[dict] | None:
    match = re.search(r"subtitles:\s*(\[.*?\])\s*,", html, re.DOTALL)
    if not match:
        return None

    try:
        subs_data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None

    lang_map = {'polskie': 'pol', 'angielskie': 'eng', 'polish': 'pol', 'english': 'eng'}
    stremio_subs = []

    for i, sub in enumerate(subs_data):
        sub_url = sub.get('url')
        if not sub_url:
            continue

        lang_raw = (sub.get('lang') or 'pol').lower()
        lang = lang_map.get(lang_raw, 'pol')
        group = sub.get('group', 'NanaSubs')

        stremio_subs.append({
            'id': f"nanasubs-{lang}-{i}",
            'url': sub_url,
            'lang': lang,
            'label': f"{sub.get('lang', 'PL')} [{group}]",
        })

    return stremio_subs if stremio_subs else None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://nanasubs.com.pl/anime/gaikotsu-kishi-sama-tadaima-isekai-e-odekakechuu-s2/odcinek-5",
    ]

    run_tests(get_video_from_nanasubs_player, urls_to_test)
