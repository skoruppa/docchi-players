import re
import json
import base64
import ctypes
import os
import aiohttp
import yarl
from binascii import hexlify
from hashlib import sha256
from os import urandom
from time import time
from random import uniform, randint, choice
from urllib.parse import urljoin, urlparse

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from Crypto.Cipher import AES
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8
from app.utils.proxy_utils import generate_proxy_url
from config import Config

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


# Domains handled by this player
DOMAINS = ['f16px.com', 'bysesayeveum.com', 'bysetayico.com', 'bysevepoin.com', 'bysezejataos.com',
    'bysekoze.com', 'bysesukior.com', 'bysejikuar.com', 'bysefujedu.com', 'bysedikamoum.com',
    'bysebuho.com', 'byse.sx', 'filemoon.sx', 'filemoon.to', 'filemoon.in', 'filemoon.link', 'filemoon.nl',
    'filemoon.wf', 'cinegrab.com', 'filemoon.eu', 'filemoon.art', 'moonmov.pro', '96ar.com',
    'kerapoxy.cc', 'furher.in', '1azayf9w.xyz', '81u6xl9d.xyz', 'smdfs40r.skin', 'c1z39.com',
    'bf0skv.org', 'z1ekv717.fun', 'l1afav.net', '222i8x.lol', '8mhlloqo.fun', 'f51rm.com',
    'xcoic.com', 'boosteradx.online', 'streamlyplayer.online', 'bysewihe.com', 'byselapuix.com', 'byseqekaho.com',
    'embedplaybyse.top', 'rupertisdivingintoocean.com']
NAMES = ['filemoon', 'byse']

REDIRECT_DOMAINS = ['boosteradx.online', 'byse.sx']

# NOTE: Requires proxy for IP-bound extraction and stream playback
ENABLED = True


# --- Crypto helpers ---

def ft(e: str) -> bytes:
    """Base64 decode with URL-safe alphabet"""
    t = e.replace("-", "+").replace("_", "/")
    r = 0 if len(t) % 4 == 0 else 4 - len(t) % 4
    n = t + "=" * r
    return base64.b64decode(n)


def xn(e: list, version=None) -> bytes:
    """Select and join base64 decoded key parts based on version."""
    if version:
        v = int(version)
        e = [e[v - 1], e[len(e) - v]]
    t = [ft(part) for part in e]
    return b''.join(t)


def _b64urlencode(data, strip=True):
    """Base64 URL-safe encode."""
    if isinstance(data, str):
        data = data.encode()
    encoded = base64.urlsafe_b64encode(data).decode()
    if strip:
        encoded = encoded.rstrip('=')
    return encoded


def _generate_ec_keypair():
    """Generate an ECDSA P-256 key pair and return (private_key, jwk_public_key_dict)."""
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()

    # Convert x, y to base64url (32 bytes each for P-256)
    x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
    y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

    jwk = {
        "alg": "ES256",
        "crv": "P-256",
        "ext": True,
        "key_ops": ["verify"],
        "kty": "EC",
        "x": _b64urlencode(x_bytes),
        "y": _b64urlencode(y_bytes),
    }
    return private_key, jwk


def _sign_nonce(private_key, nonce: str) -> str:
    """Sign the nonce with ECDSA P-256 (SHA-256) and return base64url signature."""
    signature = private_key.sign(
        nonce.encode(),
        ec.ECDSA(hashes.SHA256())
    )
    return _b64urlencode(signature)


def _solve_pow(nonce: str, difficulty: int, max_iterations: int = 500000) -> str:
    """
    Solve Byse Proof-of-Work challenge using native C solver.
    The hash is a custom memory-hard function (NOT standard SHA-256).
    Format: hash(nonce + ":" + counter_str), check leading zero bits.
    """
    import time as _t
    start = _t.time()
    result = _solve_pow_native(nonce, difficulty, max_iterations)
    elapsed = (_t.time() - start) * 1000
    print(f"Filemoon PoW solved (native): solution={result}, difficulty={difficulty}, time={elapsed:.0f}ms")
    return result


def _solve_pow_native(nonce: str, difficulty: int, max_iterations: int) -> str:
    """Solve PoW using compiled C library for speed (~50ms for difficulty 12)."""
    lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pow_solver.so')
    lib = ctypes.CDLL(lib_path)
    lib.pow_solve.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.pow_solve.restype = ctypes.c_int

    solution_buf = ctypes.create_string_buffer(32)
    result = lib.pow_solve(nonce.encode(), difficulty, max_iterations, solution_buf, 32)

    if result >= 0:
        return solution_buf.value.decode()
    raise RuntimeError(f"PoW solver: no solution found in {max_iterations} iterations")


def _solve_pow_python(nonce: str, difficulty: int, max_iterations: int) -> str:
    """Pure Python fallback PoW solver (slow but functional)."""
    BUFFER_SIZE = 512
    BUFFER_MASK = 511
    INIT_CONST = 2654435761
    FINAL_CONST = 2246822519
    MASK32 = 0xFFFFFFFF

    def _rl(val, shift):
        return ((val << shift) | (val >> (32 - shift))) & MASK32

    prefix = (nonce + ":").encode('latin-1')

    for counter in range(max_iterations):
        input_bytes = prefix + str(counter).encode('latin-1')

        s0, s1, s2, s3 = 1779033703, 3144134277, 1013904242, 2773480762

        for b in input_bytes:
            s0 = (s0 + b) & MASK32
            s0 = _rl(s0, 7)
            s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 16)
            s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 12)
            s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 8)
            s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 7)

        for _ in range(8):
            s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 16)
            s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 12)
            s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 8)
            s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 7)

        buf = [0] * BUFFER_SIZE
        for i in range(BUFFER_SIZE):
            s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 16)
            s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 12)
            s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 8)
            s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 7)
            buf[i] = (s0 ^ s2) & MASK32

        for _ in range(2):
            for si in range(BUFFER_SIZE):
                a = buf[si] & BUFFER_MASK
                c = (buf[si] + buf[a]) & MASK32
                c = _rl(c, 13)
                c = (c ^ ((buf[(si + 1) & BUFFER_MASK] * INIT_CONST) & MASK32)) & MASK32
                buf[si] = c
                s0 = (s0 ^ c) & MASK32
                s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 16)
                s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 12)
                s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 8)
                s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 7)

        s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 16)
        s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 12)
        s0 = (s0 + s1) & MASK32; s3 = _rl(s3 ^ s0, 8)
        s2 = (s2 + s3) & MASK32; s1 = _rl(s1 ^ s2, 7)

        out_val = s0
        for ci in range(64):
            d = buf[ci]
            out_val = (out_val + d) & MASK32
            out_val = _rl(out_val, 5)
            out_val = (out_val ^ ((d * FINAL_CONST) & MASK32)) & MASK32
        out_val = (out_val ^ s2) & MASK32

        leading = 32 - out_val.bit_length() if out_val > 0 else 32
        if leading >= difficulty:
            return str(counter)

    raise RuntimeError(f"PoW solver (Python): no solution found in {max_iterations} iterations")


def _generate_client_fingerprint():
    """Generate a realistic-looking client fingerprint for the attest request."""
    screen_widths = [1920, 2560, 1366, 1440, 1680]
    screen_heights = [1080, 1440, 768, 900, 1050]
    idx = randint(0, len(screen_widths) - 1)

    webgl_vendors = ["Intel", "NVIDIA Corporation", "AMD"]
    webgl_renderers = [
        "Intel(R) HD Graphics, or similar",
        "ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.5)",
        "ANGLE (NVIDIA, NVIDIA GeForce GTX 1070, OpenGL 4.5)",
        "Mesa Intel(R) UHD Graphics 620 (KBL GT2)",
    ]

    # Generate random hashes for canvas, audio, webgl, fonts, codecs
    def rand_hash():
        return _b64urlencode(urandom(32))

    return {
        "user_agent": get_random_agent(),
        "pixel_ratio": choice([1, 2]),
        "screen_width": screen_widths[idx],
        "screen_height": screen_heights[idx],
        "color_depth": 24,
        "languages": ["pl", "en-US", "en"],
        "timezone": "Europe/Warsaw",
        "hardware_concurrency": choice([4, 8, 12, 16]),
        "touch_points": 0,
        "webgl_vendor": choice(webgl_vendors),
        "webgl_renderer": choice(webgl_renderers),
        "canvas_hash": rand_hash(),
        "audio_hash": rand_hash(),
        "webgl_params_hash": rand_hash(),
        "fonts_hash": rand_hash(),
        "codecs_hash": rand_hash(),
        "media_devices": "ai0ao0vi0",
        "pointer_type": "fine,hover",
        "extra": {"vendor": "", "appVersion": "5.0 (X11)"}
    }


def _build_fingerprint_payload(token: str, viewer_id: str, device_id: str, confidence: float):
    """Build the fingerprint dict used in captcha and playback requests."""
    return {
        "fingerprint": {
            "token": token,
            "viewer_id": viewer_id,
            "device_id": device_id,
            "confidence": confidence,
        }
    }


# --- Embed origin mapping per translator ---
# Some uploaders define a specific domain for embed origin headers.
# Map translator names (lowercased) to their embed domain.
TRANSLATOR_EMBED_ORIGINS = {
    'desu-online': 'desu-online.pl',
}


# --- Stream processing ---

async def process_stream_url(session: aiohttp.ClientSession, stream_url: str, headers: dict, url: str) -> tuple:
    """Process stream URL and return final URL, quality, and headers."""
    if stream_url.startswith('/'):
        stream_url = urljoin(url, stream_url)
    stream_headers = {'request': headers}

    if PROXIFY_STREAMS:
        stream_url = await generate_proxy_url(
            session,
            stream_url,
            '/proxy/hls/manifest.m3u8',
            request_headers=headers
        )
        stream_headers = None

    try:
        quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
    except Exception:
        quality = "unknown"

    return stream_url, quality, stream_headers


# --- New challenge flow (June 2025+) ---

async def _proxy_get(session: aiohttp.ClientSession, url: str, headers: dict,
                     extra_headers: dict = None, timeout: int = 5):
    """GET request through proxy (if PROXIFY_STREAMS) or directly."""
    if PROXIFY_STREAMS:
        user_agent = headers.get("User-Agent", "")
        referer = headers.get("Referer", "")

        forward_url = (
            f'{STREAM_PROXY_URL}/proxy/stream?d={url}'
            f'&api_password={STREAM_PROXY_PASSWORD}'
            f'&h_user-agent={user_agent}'
            f'&h_referer={referer}'
        )
        if extra_headers:
            for k, v in extra_headers.items():
                forward_url += f'&h_{k.lower()}={v}'

        async with session.get(forward_url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            return await resp.json()
    else:
        all_headers = dict(headers)
        if extra_headers:
            all_headers.update(extra_headers)
        async with session.get(url, headers=all_headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _proxy_post(session: aiohttp.ClientSession, url: str, headers: dict, json_data: dict = None,
                      extra_headers: dict = None, timeout: int = 5):
    """POST request through proxy (if PROXIFY_STREAMS) or directly."""
    if PROXIFY_STREAMS:
        # Build proxy forward URL with headers as params
        user_agent = headers.get("User-Agent", "")
        referer = headers.get("Referer", "")
        origin = headers.get("Origin", "")

        forward_url = (
            f'{STREAM_PROXY_URL}/proxy/forward?d={url}'
            f'&api_password={STREAM_PROXY_PASSWORD}'
            f'&h_user-agent={user_agent}'
            f'&h_referer={referer}'
            f'&h_origin={origin}'
            f'&h_content-type=application/json'
        )
        # Add extra headers (X-Embed-*, X-Captcha-Token, cookies)
        if extra_headers:
            for k, v in extra_headers.items():
                forward_url += f'&h_{k.lower()}={v}'

        async with session.post(forward_url, json=json_data, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            return await resp.json()
    else:
        all_headers = dict(headers)
        if extra_headers:
            all_headers.update(extra_headers)
        async with session.post(url, headers=all_headers, json=json_data, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _do_challenge_flow(session: aiohttp.ClientSession, host: str, media_id: str, headers: dict, embed_url: str, translator: str = '', embed_prefix: str = 'embed/'):
    """
    Perform the full challenge flow:
    1. /api/videos/access/challenge
    2. /api/videos/access/attest
    3. /api/videos/{id}/{embed_prefix}captcha (PoW)
    4. /api/videos/{id}/{embed_prefix}captcha/verify
    5. /api/videos/{id}/{embed_prefix}playback (with X-Captcha-Token)
    """
    base = f"https://{host}"
    user_agent = headers["User-Agent"]

    # Determine embed origin based on translator
    translator_lower = translator.lower().strip() if translator else ''
    embed_origin_domain = TRANSLATOR_EMBED_ORIGINS.get(translator_lower, 'docchi.pl')

    page_referer = f'https://{embed_origin_domain}/'

    # Base headers for all API requests in this flow
    api_headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Referer": page_referer,
        "Origin": base,
    }

    # Extra headers for embed endpoints
    embed_extra = {
        "X-Embed-Origin": embed_origin_domain,
        "X-Embed-Referer": f"https://{embed_origin_domain}/",
        "X-Embed-Parent": embed_url,
    }

    # --- Step 1: Challenge ---
    challenge_url = f"{base}/api/videos/access/challenge"
    challenge_data = await _proxy_post(session, challenge_url, api_headers, json_data={})

    challenge_id = challenge_data["challenge_id"]
    nonce = challenge_data["nonce"]

    # --- Step 2: Attest ---
    private_key, public_key_jwk = _generate_ec_keypair()
    signature = _sign_nonce(private_key, nonce)
    client_fp = _generate_client_fingerprint()
    client_fp["user_agent"] = user_agent

    attest_url = f"{base}/api/videos/access/attest"
    attest_payload = {
        "viewer_id": "",
        "device_id": "",
        "challenge_id": challenge_id,
        "nonce": nonce,
        "signature": signature,
        "public_key": public_key_jwk,
        "client": client_fp,
        "storage": {},
        "attributes": {"entropy": "low"}
    }

    attest_data = await _proxy_post(session, attest_url, api_headers, attest_payload, timeout=12)

    token = attest_data["token"]
    viewer_id = attest_data["viewer_id"]
    device_id = attest_data["device_id"]
    confidence = attest_data["confidence"]

    # Set cookies for subsequent requests (only needed for non-proxy mode)
    if not PROXIFY_STREAMS:
        session.cookie_jar.update_cookies({
            "byse_viewer_id": viewer_id,
            "byse_device_id": device_id,
        }, response_url=yarl.URL(base))

    embed_extra["Cookie"] = f"byse_viewer_id={viewer_id}; byse_device_id={device_id}"

    # --- Step 3: Captcha (get PoW challenge) ---
    captcha_url = f"{base}/api/videos/{media_id}/{embed_prefix}captcha"
    fp_payload = _build_fingerprint_payload(token, viewer_id, device_id, confidence)

    captcha_data = await _proxy_post(session, captcha_url, api_headers, fp_payload, embed_extra)

    pow_nonce = captcha_data["pow_nonce"]
    pow_difficulty = captcha_data["pow_difficulty"]
    pow_token = captcha_data["pow_token"]

    # --- Step 4: Solve PoW and verify ---
    solution = _solve_pow(pow_nonce, pow_difficulty)

    verify_url = f"{base}/api/videos/{media_id}/{embed_prefix}captcha/verify"
    verify_payload = {
        "pow_token": pow_token,
        "solution": solution,
        "fingerprint": fp_payload["fingerprint"],
    }

    verify_data = await _proxy_post(session, verify_url, api_headers, verify_payload, embed_extra)

    if verify_data.get("status") != "ok":
        raise Exception(f"PoW verification failed: {verify_data}")

    captcha_token = verify_data["token"]

    # --- Step 5: Get playback with captcha token ---
    playback_url = f"{base}/api/videos/{media_id}/{embed_prefix}playback"
    playback_extra = dict(embed_extra)
    playback_extra["X-Captcha-Token"] = captcha_token

    data = await _proxy_post(session, playback_url, api_headers, fp_payload, playback_extra)

    return data


def _build_legacy_fingerprint():
    """Build the old-style fingerprint for legacy /playback endpoint."""
    v_id = hexlify(urandom(16)).decode()
    d_id = hexlify(urandom(16)).decode()
    ctime = int(time())
    t_data = {
        'viewer_id': v_id,
        'device_id': d_id,
        'confidence': round(uniform(0.6, 0.9), 2),
        'iat': ctime,
        'exp': ctime + 600
    }
    t_bdata = _b64urlencode(json.dumps(t_data))
    t_sig = _b64urlencode(sha256(t_bdata.encode()).digest())
    token = f'{t_bdata}.{t_sig}'
    t_data.update({'token': token})
    t_data.pop('iat')
    t_data.pop('exp')
    return {'fingerprint': t_data}


# --- Main entry point ---

async def get_video_from_filemoon_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False, translator: str = ''):
    """
    Extract video URL from Filemoon/Byse player.
    Flow: /details → /settings → (challenge flow if captcha_required, else simple playback)
    """
    if not is_vip and not Config.FORCE_VIP_PLAYERS:
        return None, None, None

    try:
        # Extract media_id from URL
        pattern = r'/(?:e|eyi|d|download|j\d+)/([0-9a-zA-Z]+)'
        match = re.search(pattern, url)

        if not match:
            print("Filemoon Player Error: Invalid URL format")
            return None, None, None

        media_id = match.group(1)
        parsed = urlparse(url)
        host = parsed.netloc

        # Redirect domains (static list)
        if host in REDIRECT_DOMAINS or host == 'filemoon.to':
            host = 'streamlyplayer.online'

        ref = f"https://{host}/"
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": ref,
            "Origin": ref.rstrip('/')
        }

        # Step 1: Get /details to find embed_frame_url (resolves host without redirect check)
        embed_prefix = ''
        details_url = f"https://{host}/api/videos/{media_id}/details"
        try:
            details = await _proxy_get(session, details_url, headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                # Try with embed/ prefix
                embed_prefix = 'embed/'
                details_url = f"https://{host}/api/videos/{media_id}/{embed_prefix}details"
                details = await _proxy_get(session, details_url, headers)
            else:
                raise

        # If embed_frame_url exists, use that host for subsequent requests
        embed_frame_url = details.get('embed_frame_url')
        if embed_frame_url:
            embed_parsed = urlparse(embed_frame_url)
            if embed_parsed.netloc:
                host = embed_parsed.netloc
                ref = f"https://{host}/"
                headers.update({
                    "Referer": ref,
                    "Origin": ref.rstrip('/'),
                    "X-Embed-Parent": f"https://{parsed.netloc}/e/{media_id}",
                })

        # Step 2: Get /settings to check if captcha is required
        settings_url = f"https://{host}/api/videos/{media_id}/{embed_prefix}settings"
        settings = await _proxy_get(session, settings_url, headers)

        # Step 3: Either challenge flow or simple playback
        data = None
        if settings.get('captcha_required'):
            # Full challenge flow (slow: ~8-10s due to attest)
            embed_url = f"https://{host}/e/{media_id}"
            data = await _do_challenge_flow(session, host, media_id, headers, embed_url, translator, embed_prefix)
        else:
            # Simple playback without captcha (fast: ~1s)
            playback_url = f"https://{host}/api/videos/{media_id}/{embed_prefix}playback"
            data = await _proxy_post(session, playback_url, headers, _build_legacy_fingerprint())

        if not data:
            print("Filemoon Player Error: Empty response")
            return None, None, None

        sources = None

        # Try plain sources first
        if data.get('sources'):
            sources = data.get('sources')

        # Try encrypted playback data
        if not sources and data.get('playback'):
            pd = data.get('playback')
            try:
                iv = ft(pd.get('iv'))
                key = xn(pd.get('key_parts'), pd.get('version'))
                payload = ft(pd.get('payload'))

                # AES-GCM: last 16 bytes are the authentication tag
                ciphertext = payload[:-16]
                tag = payload[-16:]

                cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
                decrypted = cipher.decrypt_and_verify(ciphertext, tag)
                ct = json.loads(decrypted.decode('latin-1'))
                sources = ct.get('sources')
            except Exception as e:
                print(f"Filemoon Decryption Error: {e}")

        if sources:
            sources_list = [x.get('url') for x in sources if x.get('url')]
            if sources_list:
                stream_url = sources_list[0]
                if stream_url.startswith('/'):
                    stream_url = urljoin(f"https://{host}/", stream_url)
                return await process_stream_url(session, stream_url, headers, url)

        print("Filemoon Player Error: No video sources found")
        return None, None, None

    except Exception as e:
        print(f"Filemoon Player Error: {type(e).__name__}: {e or 'no details'}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://bysesukior.com/e/88vt8qvbcclg",
    ]

    run_tests(get_video_from_filemoon_player, urls_to_test, True, translator='Desu-Online')
