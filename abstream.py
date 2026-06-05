import re
import aiohttp
from urllib.parse import urlparse
from app.utils.common_utils import get_random_agent

DOMAINS = ['abstream.to']
NAMES = ['abstream']

ENABLED = True


async def get_video_from_abstream_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    """Extract video URL from AbStream player"""

    parsed = urlparse(player_url)
    host = parsed.hostname
    path = parsed.path.rstrip('/')
    video_id = path.split('/')[-1].replace('.html', '').replace('embed-', '')

    # Use embed URL format
    embed_url = f"https://{host}/embed-{video_id}.html"
    user_agent = get_random_agent()

    try:
        headers = {
            'User-Agent': user_agent,
        }

        async with session.get(embed_url, headers=headers, allow_redirects=True) as response:
            html = await response.text()

        # Pattern from ResolveURL: sources: [{ file: 'URL' }]
        match = re.search(r'''sources:\s*\[{\s*file\s*:\s*['"](?P<url>[^'"]+)''', html)
        if not match:
            # Fallback: any sources/file pattern
            match = re.search(r'''(?:file|src)\s*[:=]\s*["']([^"']+\.m3u8[^"']*)''', html)
            if not match:
                match = re.search(r'''(?:file|src)\s*[:=]\s*["']([^"']+\.mp4[^"']*)''', html)

        if not match:
            print("AbStream Player Error: No video source found")
            return None, None, None

        final_url = match.group('url') if 'url' in match.groupdict() else match.group(1)

        # Try to detect quality
        quality = 'unknown'
        quality_match = re.search(r'\b(360|480|720|1080|1440|2160)[pP]?', html)
        if quality_match:
            quality = f"{quality_match.group(1)}p"

        stream_headers = {'request': {'User-Agent': user_agent}}
        return final_url, quality, stream_headers

    except Exception as e:
        print(f"AbStream Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://abstream.to/embed/blshnz6jt14e"
    ]

    run_tests(get_video_from_abstream_player, urls_to_test)
