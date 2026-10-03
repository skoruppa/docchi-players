import re
import logging
import aiohttp
from app.utils.common_utils import get_random_agent, get_packed_data, fetch_resolution_from_m3u8
from app.utils.proxy_utils import generate_proxy_url, proxy_get
from config import Config

DOMAINS = ['vidmoly.me', 'vidmoly.to', 'vidmoly.net', 'vidmoly.biz', 'vidmoly.org']
NAMES = ['vidmoly']

PROXIFY_STREAMS = Config.PROXIFY_STREAMS


async def get_video_from_vidmoly_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    if not is_vip and not Config.FORCE_VIP_PLAYERS:
        return None, None, None

    try:
        match = re.search(
            r'(?://|\.)(vidmoly\.(?:me|to|net|biz|org))/(?:embed-|w/|v/|dl/)?([0-9a-zA-Z]+)',
            url
        )
        if not match:
            logging.warning("[VidMoly] Could not extract media ID")
            return None, None, None

        host = match.group(1)
        media_id = match.group(2)
        embed_url = f'https://{host}/embed-{media_id}.html'
        user_agent = get_random_agent()
        headers = {'User-Agent': user_agent, 'Referer': embed_url}

        if PROXIFY_STREAMS:
            html, proxy_idx = await proxy_get(session, embed_url, headers)
            if not html:
                logging.warning("[VidMoly] Failed to fetch embed page via proxy")
                return None, None, None
        else:
            async with session.get(embed_url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    logging.warning(f"[VidMoly] Page returned status {response.status}")
                    return None, None, None
                html = await response.text()

        stream_url = _extract_source(html)
        if not stream_url:
            packed = get_packed_data(html)
            if packed:
                stream_url = _extract_source(packed)

        if not stream_url:
            logging.warning("[VidMoly] No video source found")
            return None, None, None

        if stream_url.endswith('.mpd'):
            logging.warning("[VidMoly] Only DASH source found, skipping")
            return None, None, None

        quality = 'unknown'
        if '.m3u8' in stream_url:
            try:
                quality = await fetch_resolution_from_m3u8(
                    session, stream_url, headers, use_proxy=PROXIFY_STREAMS
                ) or 'unknown'
            except Exception:
                pass
            if quality == 'unknown':
                try:
                    if PROXIFY_STREAMS:
                        text, _ = await proxy_get(session, stream_url, headers, timeout=3)
                        if text:
                            res = re.findall(r'RESOLUTION=\s*(\d+)x(\d+)', text)
                            if res:
                                quality = f"{max(int(h) for w, h in res)}p"
                    else:
                        async with session.get(stream_url, headers=headers,
                                               timeout=aiohttp.ClientTimeout(total=3)) as m3u8_resp:
                            if m3u8_resp.status == 200:
                                text = await m3u8_resp.text()
                                res = re.findall(r'RESOLUTION=\s*(\d+)x(\d+)', text)
                                if res:
                                    quality = f"{max(int(h) for w, h in res)}p"
                except Exception:
                    pass
        else:
            qm = re.search(r'(\d{3,4})[pP]', stream_url)
            if qm:
                quality = f'{qm.group(1)}p'

        if PROXIFY_STREAMS:
            stream_url = await generate_proxy_url(
                session, stream_url,
                '/proxy/hls/manifest.m3u8' if '.m3u8' in stream_url else '/proxy/stream',
                request_headers=headers,
            )
            return stream_url, quality, None

        return stream_url, quality, {'request': {'User-Agent': user_agent, 'Referer': embed_url}}

    except Exception as e:
        logging.warning(f"[VidMoly] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


def _extract_source(text: str) -> str | None:
    matches = re.findall(r'''sources\s*:\s*\[\s*\{\s*file\s*:\s*['"]([^'"]+)['"]''', text)
    for src in matches:
        if not src.endswith('.mpd'):
            return src
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
