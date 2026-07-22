import re
import json
import time
import random
import hashlib
import binascii
import logging
import asyncio
import aiohttp
from ast import literal_eval
from base64 import b64decode
from urllib.parse import urljoin, urlparse

from Crypto.Cipher import AES
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['drakkar.st']
NAMES = ['drakkar']

ENABLED = True


def _xd(enc, key):
    """
    XOR decrypt.
    - If enc is a list of ints and key is a list of ints: chr(enc[i] ^ key[i])
    - If enc is a string (hex) and key is a string: format(int(enc[i],16) ^ int(key[i%len(key)],16), 'x')
    - If enc is a list of ints and key is a string: chr(enc[i] ^ ord(key[i%len(key)]))
    """
    r = ''
    for i in range(len(enc)):
        if isinstance(enc, list) and isinstance(enc[i], int):
            if isinstance(key, list):
                r += chr(enc[i] ^ key[i % len(key)])
            else:
                r += chr(enc[i] ^ ord(key[i % len(key)]))
        else:
            # Both enc[i] and key element are hex characters
            k = key[i % len(key)] if isinstance(key, str) else str(key[i % len(key)])
            r += format(int(enc[i], 16) ^ int(k, 16), 'x')
    return r


def _wc(seed, ch):
    """Generate SHA-256 based challenge hash."""
    return hashlib.sha256((seed + ch).encode('utf-8')).hexdigest()[:16]


def _dec(d, iv, p1, p2, p3, p4, iphash, cr):
    """Decrypt main payload using AES-CBC with compound key."""
    try:
        key = hashlib.sha256((p1 + p2 + p3 + p4 + cr + iphash).encode()).digest()
        cipher = AES.new(key, AES.MODE_CBC, binascii.unhexlify(iv))
        decrypted = cipher.decrypt(b64decode(d))
        # Remove PKCS7 padding
        pad_len = decrypted[-1]
        if pad_len <= 16:
            decrypted = decrypted[:-pad_len]
        return decrypted.decode()
    except Exception:
        return None


def _decsimple(d, iv, k1, k2, k3, k4):
    """Decrypt simple AES-CBC payload with hex key parts."""
    try:
        key = binascii.unhexlify(k1 + k2 + k3 + k4)
        if len(key) not in [16, 24, 32]:
            return None
        cipher = AES.new(key, AES.MODE_CBC, binascii.unhexlify(iv))
        decrypted = cipher.decrypt(b64decode(d))
        pad_len = decrypted[-1]
        if pad_len <= 16:
            decrypted = decrypted[:-pad_len]
        return decrypted.decode()
    except Exception:
        return None


async def get_video_from_drakkar_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from Drakkar player."""
    try:
        match = re.search(r'/v/([0-9a-zA-Z\-_]+)', url)
        if not match:
            logging.warning("[Drakkar] Invalid URL format")
            return None, None, None

        media_id = match.group(1)
        parsed = urlparse(url)
        host = parsed.netloc
        web_url = f"https://{host}/v/{media_id}"

        user_agent = get_random_agent()
        headers = {
            "User-Agent": user_agent,
        }

        # Step 1: Fetch the embed page
        async with session.get(web_url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            html = await response.text()

        # Step 2: Extract crypto params from inline script
        r = re.search(
            r"\(function\(\){\s*(var.+?)\s*var\s*_cr.+?_ept\s*=\s*'([^']+).+?_ws\s*=\s*'([^']+)",
            html, re.DOTALL
        )

        if not r:
            # Try alternative pattern
            r = re.search(
                r"\(function\(\)\s*{\s*(var.+?)\s*var\s+_cr.+?_ept\s*=\s*'([^']+).+?_ws\s*=\s*'([^']+)",
                html, re.DOTALL
            )

        if not r:
            logging.warning("[Drakkar] Could not find crypto params in page")
            logging.debug(f"[Drakkar] Page length: {len(html)}, contains 'function': {'function' in html}")
            return None, None, None

        _ts = int(time.time() * 1000)

        # Simulate browser delay (server expects ~1.5s between page load and stream request)
        await asyncio.sleep(1.5)

        # Parse _cr value based on obfuscation type
        if 'fromCharCode' in r.group(1):
            s = re.findall(r'=\s*(\[[^;]+)', r.group(1))
            if len(s) == 2:
                _cr = _xd(literal_eval(s[0]), literal_eval(s[1]))
            else:
                t = int(r.group(1)[:-2].split(']')[-1])
                _cr = ''
                for i in literal_eval(s[0]):
                    _cr += chr(i + t)
        else:
            s = re.findall(r"=((?:atob\()?'[^']+)", r.group(1))
            if 'atob(' in s[0]:
                _cr = b64decode(s[0].split("'")[-1]).decode() + b64decode(s[1].split("'")[-1]).decode()
            else:
                _cr = s[0].split("'")[-1][::-1] + s[1].split("'")[-1][::-1]

        # Build POST payload
        data = {
            'cr': _cr,
            'pt': _xd(r.group(2), _cr),
            'wc': _wc(r.group(3), _cr),
            '_ts2': int(time.time() * 1000) - random.randint(100, 500),
            'bs': {
                'ts': _ts,
                'sw': 1280,
                'sh': 720,
                'plt': '',
                'tz': 240,
                'lang': 'en-US',
                'pl': '',
                'ct': 4,
                'dm': 24,
                'td': 0,
                'cv': 1,
                'wg': 1
            }
        }

        ref = urljoin(web_url, '/')
        headers.update({
            'Referer': web_url,
            'Origin': ref.rstrip('/'),
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/plain, */*',
            'X-Requested-With': 'XMLHttpRequest',
        })

        # Step 3: POST to /stream endpoint
        stream_api_url = web_url + '/stream'
        async with session.post(stream_api_url, json=data, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            res = await response.json()

        if not all([res.get('s'), res.get('d'), res.get('x')]):
            logging.warning("[Drakkar] Incomplete stream response")
            return None, None, None

        # Step 4: Decrypt payload
        payload = _dec(
            res.get('d'), res.get('v'),
            res.get('p1'), res.get('p2'), res.get('p3'), res.get('p4'),
            res.get('x'), _cr
        )

        result_html = None
        if payload:
            payload_data = json.loads(payload)
            epd = payload_data.get('encrypted_player_data')
            if epd and epd.get('ct'):
                result_html = _decsimple(
                    epd.get('ct'), epd.get('iv'),
                    epd.get('k1'), epd.get('k2'), epd.get('k3'), epd.get('k4')
                )
            elif payload_data.get('processed_template'):
                result_html = payload_data.get('processed_template')

        if not result_html:
            logging.warning("[Drakkar] Failed to decrypt player data")
            return None, None, None

        # Step 5: Extract video URL
        video_match = re.search(r"videoSrc:\s*'([^']+)", result_html)
        if not video_match:
            logging.warning("[Drakkar] No videoSrc found in decrypted data")
            return None, None, None

        stream_url = video_match.group(1)

        stream_headers = {
            'request': {
                "User-Agent": user_agent,
                "Referer": ref,
                "Origin": ref.rstrip('/')
            }
        }

        try:
            quality = await fetch_resolution_from_m3u8(session, stream_url, stream_headers['request']) or "unknown"
        except Exception:
            quality = "unknown"
        return stream_url, quality, stream_headers

    except Exception as e:
        logging.warning(f"[Drakkar] {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://drakkar.st/v/piX4kv6BtrV",
    ]

    run_tests(get_video_from_drakkar_player, urls_to_test)
