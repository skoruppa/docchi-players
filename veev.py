import re
import json
import binascii
import aiohttp
from urllib.parse import urljoin, urlencode, urlparse
from app.utils.common_utils import get_random_agent

DOMAINS = ['veev.to', 'poophq.com', 'doods.to']
NAMES = ['veev']

ENABLED = True


def veev_decode(etext):
    """LZW-style string decompression used by Veev player."""
    result = []
    lut = {}
    n = 256
    c = etext[0]
    result.append(c)
    for char in etext[1:]:
        code = ord(char)
        nc = char if code < 256 else lut.get(code, c + c[0])
        result.append(nc)
        lut[n] = c + nc[0]
        n += 1
        c = nc
    return ''.join(result)


def js_int(x):
    return int(x) if x.isdigit() else 0


def build_array(encoded_string):
    d = []
    c = list(encoded_string)
    count = js_int(c.pop(0))
    while count:
        current_array = []
        for _ in range(count):
            current_array.insert(0, js_int(c.pop(0)))
        d.append(current_array)
        count = js_int(c.pop(0))
    return d


def decode_url(etext, tarray):
    ds = etext
    for t in tarray:
        if t == 1:
            ds = ds[::-1]
        ds = binascii.unhexlify(ds).decode('utf8')
        ds = ds.replace('dXRmOA==', '')
    return ds


async def get_video_from_veev_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    """Extract video URL from Veev player"""

    parsed = urlparse(player_url)
    host = parsed.hostname
    video_id = parsed.path.rstrip('/').split('/')[-1]

    web_url = f"https://{host}/e/{video_id}"
    user_agent = get_random_agent()

    try:
        headers = {
            'User-Agent': user_agent,
            'Referer': web_url
        }

        async with session.get(web_url, headers=headers, allow_redirects=True) as response:
            actual_url = str(response.url)
            html = await response.text()

        # Update media_id if redirected
        if actual_url != web_url:
            video_id = actual_url.rstrip('/').split('/')[-1]

        # Extract encoded tokens from page
        items = re.findall(r'''[\.\s'](?:fc|_vvto\[[^\]]*)(?:['\]]*)?\s*[:=]\s*['"]([^'"]+)''', html)
        if not items:
            print("Veev Player Error: No encoded tokens found")
            return None, None, None

        for f in items[::-1]:
            ch = veev_decode(f)
            if ch != f:
                params = {
                    'op': 'player_api',
                    'cmd': 'gi',
                    'file_code': video_id,
                    'ch': ch,
                    'ie': 1
                }
                durl = urljoin(web_url, '/dl') + '?' + urlencode(params)

                async with session.get(durl, headers=headers, allow_redirects=True) as response:
                    jresp = await response.json(content_type=None)

                file_data = jresp.get('file')
                if file_data and file_data.get('file_status') == 'OK':
                    dv = file_data.get('dv', [])
                    if not dv:
                        continue

                    encoded_stream = dv[0].get('s')
                    if not encoded_stream:
                        continue

                    decoded_stream = veev_decode(encoded_stream)
                    arr = build_array(ch)
                    if not arr:
                        continue

                    final_url = decode_url(decoded_stream, arr[0])

                    # Try to get quality from dv entry
                    quality = 'unknown'
                    q = dv[0].get('q')
                    if q:
                        quality_match = re.search(r'\b(360|480|720|1080|1440|2160)[pP]?', str(q))
                        if quality_match:
                            quality = f"{quality_match.group(1)}p"

                    stream_headers = {'request': {'Referer': web_url, 'User-Agent': user_agent}}
                    return final_url, quality, stream_headers

        print("Veev Player Error: Unable to locate video")
        return None, None, None

    except Exception as e:
        print(f"Veev Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://veev.to/e/2EvjtvNM7IF2vqAWgGH8ug7pAb9eIlagSuKIInw"
    ]

    run_tests(get_video_from_veev_player, urls_to_test)
