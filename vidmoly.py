import re
import logging
import aiohttp
from app.utils.common_utils import get_random_agent, get_packed_data, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['vidmoly.me', 'vidmoly.to', 'vidmoly.net', 'vidmoly.biz', 'vidmoly.org']
NAMES = ['vidmoly']


async def get_video_from_vidmoly_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from VidMoly player."""
    try:
        # Extract media_id from URL
        match = re.search(
            r'(?://|\.)(vidmoly\.(?:me|to|net|biz|org))/(?:embed-|w/|v/|dl/)?([0-9a-zA-Z]+)',
            url
        )
        if not match:
            logging.warning("[VidMoly] Could not extract media ID from URL")
            return None, None, None

        host = match.group(1)
        media_id = match.group(2)

        embed_url = f'https://{host}/embed-{media_id}.html'
        user_agent = get_random_agent()

        headers = {
            'User-Agent': user_agent,
            'Referer': embed_url,
        }

        async with session.get(embed_url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=8)) as response:
            if response.status != 200:
                logging.warning(f"[VidMoly] Page returned status {response.status}")
                return None, None, None
            html = await response.text()

        # Try to find stream URL in sources pattern
        stream_url = _extract_source(html)

        # Fallback: try packed/eval data
        if not stream_url:
            packed = get_packed_data(html)
            if packed:
                stream_url = _extract_source(packed)

        if not stream_url:
            logging.warning("[VidMoly] No video source found")
            return None, None, None

        # Skip .mpd sources (DASH), prefer HLS/MP4
        if stream_url.endswith('.mpd'):
            logging.warning("[VidMoly] Only DASH source found, skipping")
            return None, None, None

        stream_headers = {
            'request': {
                'User-Agent': user_agent,
                'Referer': embed_url,
            }
        }

        # Detect quality
        quality = 'unknown'
        if '.m3u8' in stream_url:
            try:
                quality = await fetch_resolution_from_m3u8(
                    session, stream_url, stream_headers['request']
                ) or 'unknown'
            except Exception:
                pass
            # Fallback: fetch m3u8 directly with aiohttp if tls-client failed
            if quality == 'unknown':
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
        else:
            quality_match = re.search(r'(\d{3,4})[pP]', stream_url)
            if quality_match:
                quality = f'{quality_match.group(1)}p'

        return stream_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[VidMoly] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


def _extract_source(text: str) -> str | None:
    """Extract stream URL from HTML/JS text, skipping .mpd sources."""
    # Pattern: sources:[{file:"URL"}] or sources: [{file: "URL"}]
    matches = re.findall(
        r'''sources\s*:\s*\[\s*\{\s*file\s*:\s*['"]([^'"]+)['"]''',
        text
    )
    for src in matches:
        if not src.endswith('.mpd'):
            return src
    # Fallback: generic source src="URL"
    match = re.search(r'''source\s+src=["']([^"']+)["']''', text)
    if match and not match.group(1).endswith('.mpd'):
        return match.group(1)
    return None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://vidmoly.org/embed-rqm35drkcil1.html",
    ]

    run_tests(get_video_from_vidmoly_player, urls_to_test)
