import asyncio
import logging
import aiohttp
import base64
import json
from bs4 import BeautifulSoup
from aiocache import cached
from aiocache.serializers import PickleSerializer
from app.players.rumble import get_video_from_rumble_player
from app.utils.common_utils import get_random_agent
from config import Config

# Domains handled by this player
DOMAINS = ['lycoris.cafe']
NAMES = ['lycoris']

DECRYPT_API_KEY = "303a897d-sd12-41a8-84d1-5e4f5e208878"
PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD

async def check_url_status(session, url):
    if PROXIFY_STREAMS:
        url = f'{STREAM_PROXY_URL}/proxy/stream?d={url}&api_password={STREAM_PROXY_PASSWORD}'
    try:
        async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status not in (405, 501):
                return resp.status
    except Exception:
        pass

    try:
        async with session.get(url, headers={"Range": "bytes=0-0"}, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            return resp.status
    except Exception:
        return None

_compat_ua = "Mozilla/5.0 (Windows; U; MSIE 5.01; Windows NT 4.0; Netscape6/6.2; Gecko/20010726)"


@cached(ttl=50, serializer=PickleSerializer())
async def get_video_from_lycoris_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    user_agent = get_random_agent()
    headers = {"User-Agent": user_agent}
    rumble_url = None
    _last_step = "init"
    _timeout = aiohttp.ClientTimeout(total=5)
    
    try:
        _last_step = f"GET {url}"
        async with session.get(url, headers=headers, ssl=False, timeout=_timeout) as response:
            response.raise_for_status()
            html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')
        scripts = soup.find_all('script', {'type': 'application/json'})

        episode_id = None
        rumble_url = None

        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string.strip())
                body_str = data.get("body")
                if not body_str:
                    continue
                    
                body = json.loads(body_str)
                
                # Check for episodeInfo format
                if "episodeInfo" in body:
                    episode_info = body['episodeInfo']
                    episode_id = episode_info.get('id')
                    rumble_url = episode_info.get('rumbleLink')
                    break
                
                # Check for anime.episodes format
                anime = body.get('anime', {})
                episodes = anime.get('episodes', [])
                if episodes:
                    # Extract episode number from URL
                    import re
                    match = re.search(r'/watch/(\d+)$', url)
                    if match:
                        episode_num = int(match.group(1))
                        episode = next((ep for ep in episodes if ep.get('number') == episode_num), None)
                        if episode:
                            episode_id = episode.get('id')
                            rumble_url = episode.get('rumbleLink')
                            break
            except:
                continue

        if not episode_id:
            logging.error("[Lycoris] Episode ID not found.")
            return None, None, None

        # Get encoded video link (retry once on timeout)
        video_link_url = f"https://www.lycoris.cafe/api/watch/getVideoLink?id={episode_id}"
        _last_step = f"GET {video_link_url}"
        encrypted_text = None
        for _attempt in range(2):
            try:
                async with session.get(video_link_url, headers={"User-Agent": _compat_ua}, timeout=aiohttp.ClientTimeout(total=3)) as link_response:
                    link_response.raise_for_status()
                    encrypted_text = await link_response.text()
                    break
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
                if _attempt == 0:
                    continue  # retry once
                raise

        base64_encoded_data = base64.b64encode(encrypted_text.encode('latin-1')).decode('utf-8')

        decrypt_url = "https://www.lycoris.cafe/api/watch/decryptVideoLink"
        decrypt_headers = {
            "User-Agent": _compat_ua,
            "x-api-key": DECRYPT_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {"encoded": base64_encoded_data}

        _last_step = f"POST {decrypt_url}"
        decrypt_response_data = None
        for _attempt in range(2):
            try:
                async with session.post(decrypt_url, headers=decrypt_headers, json=payload, timeout=aiohttp.ClientTimeout(total=3)) as decrypt_response:
                    decrypt_response.raise_for_status()
                    decrypt_response_data = await decrypt_response.json()
                    break
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
                if _attempt == 0:
                    continue
                raise

        video_sources = decrypt_response_data

        highest_quality = None
        if video_sources.get('FHD'):
            highest_quality = {"url": video_sources['FHD'], 'quality': '1080p'}
        elif video_sources.get('HD'):
            highest_quality = {"url": video_sources['HD'], 'quality': '720p'}
        elif video_sources.get('SD'):
            highest_quality = {"url": video_sources['SD'], 'quality': '480p'}

        if highest_quality:
            url_candidates = [u.strip() for u in highest_quality['url'].split(' or ') if u.strip()]
            quality = highest_quality['quality']
            for url_candidate in url_candidates:
                _last_step = f"check_url_status {url_candidate}"
                status = await check_url_status(session, url_candidate)
                if status in (200, 206):
                    return url_candidate, quality, None

        # Fallback to Rumble if primary sources fail
        if rumble_url:
            return await get_video_from_rumble_player(session, rumble_url)

        return None, None, None

    except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
        logging.error(f"[Lycoris] Timeout at: {_last_step}")
        if rumble_url:
            try:
                return await get_video_from_rumble_player(session, rumble_url)
            except Exception:
                pass
        return None, None, None
    except Exception as e:
        logging.error(f"[Lycoris] An unexpected error occurred: {type(e).__name__}: {e}")
        # Try Rumble fallback if available
        if rumble_url:
            try:
                return await get_video_from_rumble_player(session, rumble_url)
            except Exception:
                pass
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://www.lycoris.cafe/embed?id=210031&episode=1",
    ]

    run_tests(get_video_from_lycoris_player, urls_to_test)