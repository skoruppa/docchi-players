import re
import logging
import aiohttp
from urllib.parse import urlparse
from app.utils.common_utils import get_random_agent

DOMAINS = ['vidoza.net', 'vidoza.co', 'videzz.net']
NAMES = ['vidoza', 'videzz']

ENABLED = True


async def get_video_from_vidoza_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    """Extract video URL from Vidoza/Videzz player"""

    parsed = urlparse(player_url)
    host = parsed.hostname
    video_id = parsed.path.rstrip('/').split('/')[-1]

    # Normalize to embed URL format
    if not video_id.startswith('embed-'):
        video_id = video_id.replace('.html', '')
        embed_url = f"https://{host}/embed-{video_id}.html"
    else:
        embed_url = f"https://{host}/{video_id}"

    user_agent = get_random_agent()

    try:
        headers = {
            'User-Agent': user_agent,
        }

        async with session.get(embed_url, headers=headers, allow_redirects=True) as response:
            html = await response.text()

        # Pattern from ResolveURL: file/src with res label
        matches = re.findall(
            r'''["']?\s*(?:file|src)\s*["']?\s*[:=,]?\s*["'](?P<url>[^"']+)(?:[^}>\]]+)["']?\s*res\s*["']?\s*[:=]\s*["']?(?P<label>[^"',]+)''',
            html
        )

        if not matches:
            # Fallback: try simpler pattern for source src with label
            matches = re.findall(
                r'''(?:file|src)\s*[:=]\s*["']([^"']+)["'].*?(?:label|res)\s*[:=]\s*["']?(\d+)''',
                html, re.DOTALL
            )

        if not matches:
            # Last fallback: any mp4 URL
            mp4_match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', html)
            if mp4_match:
                final_url = mp4_match.group(1)
                stream_headers = {'request': {'User-Agent': user_agent}}
                return final_url, 'unknown', stream_headers

            logging.warning("[Vidoza] No video sources found")
            return None, None, None

        # Pick highest quality
        best_url = None
        best_quality = 0
        for url, label in matches:
            res = re.search(r'(\d+)', str(label))
            q = int(res.group(1)) if res else 0
            if q >= best_quality:
                best_quality = q
                best_url = url

        if not best_url:
            best_url = matches[0][0]

        quality = f"{best_quality}p" if best_quality > 0 else 'unknown'
        stream_headers = {'request': {'User-Agent': user_agent}}
        return best_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[Vidoza] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://videzz.net/embed-y34qudiino2n.html"
    ]

    run_tests(get_video_from_vidoza_player, urls_to_test)
