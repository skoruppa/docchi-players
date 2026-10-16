import re
import logging
import aiohttp
import json
import urllib.parse
from app.utils.common_utils import get_random_agent
from config import Config

# Domains handled by this player
DOMAINS = ['m.cda.pl', 'cda.pl', 'www.cda.pl', 'ebd.cda.pl']
NAMES = ['cda']

PROXIFY_STREAMS = Config.PROXIFY_STREAMS

# Quality slug → numeric resolution for sorting
_Q_ORDER = {'vl': 360, 'lq': 480, 'sd': 720, 'hd': 1080}


def decrypt_url(url: str) -> str:
    """Decrypt legacy CDA obfuscated mp4 URL (kept as fallback)."""
    for p in ("_XDDD", "_CDA", "_ADC", "_CXD", "_QWE", "_Q5", "_IKSDE"):
        url = url.replace(p, "")
    url = urllib.parse.unquote(url)
    b = []
    for c in url:
        f = c if isinstance(c, int) else ord(c)
        b.append(chr(33 + (f + 14) % 94) if 33 <= f <= 126 else chr(f))
    a = "".join(b)
    a = a.replace(".cda.mp4", "")
    a = a.replace(".2cda.pl", ".cda.pl")
    a = a.replace(".3cda.pl", ".cda.pl")
    if "/upstream" in a:
        a = a.replace("/upstream", ".mp4/upstream")
        return "https://" + a
    return "https://" + a + ".mp4"


def normalize_cda_url(url):
    pattern = r"https?://(?:www\.|m\.)?cda\.pl/(?:video/)?([\w]+)(?:\?.*)?|https?://ebd\.cda\.pl/\d+x\d+/([\w]+)"
    match = re.match(pattern, url)
    if match:
        video_id = match.group(1) or match.group(2)
        return f"https://www.cda.pl/video/{video_id}", video_id
    return None, None


def get_highest_quality(qualities: dict) -> tuple:
    qualities.pop('auto', None)
    highest_quality = max(qualities.keys(), key=lambda x: int(x.rstrip('p')))
    return highest_quality, qualities[highest_quality]


def _parse_player_data(html: str) -> dict | None:
    """Extract player_data JSON from CDA HTML."""
    match = re.search(r"player_data='(.*?)'\s+tabindex", html, re.DOTALL)
    if not match:
        match = re.search(r'player_data=[\'"]([^\'"]+)[\'"]', html)
    if not match:
        return None
    try:
        raw = match.group(1).replace('&quot;', '"').replace('&#39;', "'")
        return json.loads(raw)
    except Exception:
        return None


def _build_direct_mp4_url(manifest_url: str, video_id: str, quality: str) -> str | None:
    """Build a direct mp4 URL from the manifest base path.

    CDA stores segments as ``video_{numericId}_{quality}.mp4`` next to the
    manifest.  The numeric ID is the part of video_id without trailing alpha
    chars (e.g. ``27664708b6`` → ``27664708``).
    """
    base = manifest_url.rsplit('/', 1)[0]
    numeric_id = re.match(r'(\d+)', video_id)
    if not numeric_id:
        return None
    return f"{base}/video_{numeric_id.group(1)}_{quality}.mp4"


async def _get_html(session: aiohttp.ClientSession, url: str) -> str | None:
    """Simple GET — no proxy needed, CDA streams are not IP-bound."""
    try:
        headers = {'User-Agent': get_random_agent()}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.text()
    except Exception as e:
        logging.warning(f"[CDA] GET failed: {e}")
        return None


async def _post_html(session: aiohttp.ClientSession, url: str, form_data: dict) -> str | None:
    """Simple POST — no proxy needed."""
    try:
        headers = {'User-Agent': get_random_agent()}
        data = aiohttp.FormData()
        for k, v in form_data.items():
            data.add_field(k, v)
        async with session.post(url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.text()
    except Exception as e:
        logging.warning(f"[CDA] POST failed: {e}")
        return None


async def _head_ok(session: aiohttp.ClientSession, url: str) -> bool:
    """Quick HEAD check to verify a URL is reachable (200)."""
    try:
        headers = {'User-Agent': get_random_agent()}
        async with session.head(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=True) as resp:
            return resp.status == 200
    except Exception:
        return False


async def get_video_from_cda_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False) -> tuple:
    """Extract video URL from CDA player.

    Stream priority (all are NOT IP-bound, token-time-limited only):
      1. Direct mp4 built from manifest path (best Stremio compat)
      2. Legacy encrypted ``file`` field → decrypted mp4
      3. HLS manifest (``manifest_apple``)

    No proxy is used — CDA switched to token-auth streams that work from any IP.
    """
    url, video_id = normalize_cda_url(url)
    if not url:
        return None, None, None

    try:
        # Step 1: Fetch page
        html = await _get_html(session, url)
        if not html:
            return None, None, None

        # Handle age confirmation
        if 'age_confirm' in html:
            html = await _post_html(session, url, {'age_confirm': ''})
            if not html:
                return None, None, None

        video_data = _parse_player_data(html)
        if not video_data:
            return None, None, None

        video = video_data['video']
        qualities = video.get('qualities', {})
        highest_quality, _ = get_highest_quality(dict(qualities))

        manifest_apple = video.get('manifest_apple', '')
        file_enc = video.get('file', '')

        video_headers = {"request": {"User-Agent": get_random_agent()}}

        # Step 2: Try direct mp4 from manifest base path
        if manifest_apple:
            mp4_url = _build_direct_mp4_url(manifest_apple, video_id, highest_quality)
            if mp4_url and await _head_ok(session, mp4_url):
                logging.info(f"[CDA] Direct mp4 {highest_quality}: {mp4_url[:80]}")
                return mp4_url, highest_quality, video_headers

        # Step 3: Fallback — legacy encrypted file field
        if file_enc:
            decrypted = decrypt_url(file_enc)
            if await _head_ok(session, decrypted):
                logging.info(f"[CDA] Legacy mp4: {decrypted[:80]}")
                return decrypted, highest_quality, video_headers

        # Re-fetch with explicit quality in case default didn't give us file
        if not file_enc:
            hq_url = f'{url}?wersja={highest_quality}'
            html = await _get_html(session, hq_url)
            if html:
                hq_data = _parse_player_data(html)
                if hq_data:
                    file_enc = hq_data['video'].get('file', '')
                    if file_enc:
                        decrypted = decrypt_url(file_enc)
                        if await _head_ok(session, decrypted):
                            logging.info(f"[CDA] Legacy mp4 (re-fetch): {decrypted[:80]}")
                            return decrypted, highest_quality, video_headers
                    # Update manifest in case first fetch didn't have it
                    if not manifest_apple:
                        manifest_apple = hq_data['video'].get('manifest_apple', '')

        # Step 4: Fallback — HLS manifest
        if manifest_apple:
            logging.info(f"[CDA] HLS fallback: {manifest_apple[:80]}")
            return manifest_apple, highest_quality, video_headers

        return None, None, None

    except Exception as e:
        logging.warning(f"[CDA] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://ebd.cda.pl/1055x594/27664708b6"
    ]

    run_tests(get_video_from_cda_player, urls_to_test)
