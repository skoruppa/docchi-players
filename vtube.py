"""vTube player extractor.

Based on ResolveURL plugin by shellc0de (GPL-3.0).
Rewritten for async aiohttp.
"""
import re
import logging
import aiohttp

from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['vtbe.to', 'vtbe.net', 'vtube.to', 'vtube.network', 'vtplay.net']
NAMES = ['vtube']

ENABLED = True

_ID_PATTERN = re.compile(r'(?://|\.)vt(?:u?be|play)\.(?:to|net|network)/(?:embed-)?([0-9a-zA-Z]+)')


async def get_video_from_vtube_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract HLS URL from vTube player."""
    try:
        match = _ID_PATTERN.search(url)
        if not match:
            logging.warning("[vTube] Could not extract media ID")
            return None, None, None

        # vtbe.to serves the embed for every mirror domain (vtbe.net no longer resolves)
        embed_url = f'https://vtbe.to/embed-{match.group(1)}.html'
        headers = {
            'User-Agent': get_random_agent(),
            'Referer': 'https://vtbe.to/',
        }

        async with session.get(embed_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
            response.raise_for_status()
            html = await response.text()

        source = re.search(r'''sources:\s*\[\{file:\s*["']([^"']+)''', html)
        if not source:
            # Deleted files embed a placeholder iframe instead of the player
            logging.warning("[vTube] No video source found (file removed?)")
            return None, None, None

        stream_url = source.group(1)
        quality = None
        if '.m3u8' in stream_url:
            try:
                quality = await fetch_resolution_from_m3u8(session, stream_url, headers)
            except Exception:
                pass

        return stream_url, quality or 'unknown', {'request': headers}

    except Exception as e:
        logging.warning(f"[vTube] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://vtbe.to/embed-2dg6qk0m7crv.html",
        "https://vtbe.to/embed-ae2s2q49x9ev.html",  # removed file
    ]

    run_tests(get_video_from_vtube_player, urls_to_test)
