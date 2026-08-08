# Docchi Players

A collection of async Python video player extractors for anime streaming sites. Originally built for the [Docchi Stremio Addon](https://github.com/skoruppa/docchi-stremio-addon), but designed to be reusable in any `aiohttp`-based project.

## Supported Players

| Player | Domains | Proxy Required |
|--------|---------|:-:|
| ABStream | abstream.to | |
| Abyss (HydraX) | abysscdn.com | |
| Buzzheavier | buzzheavier.com | ✓ |
| CDA | cda.pl | |
| Dailymotion | dailymotion.com | |
| DoodStream | dood.watch | |
| EarnVid / VidHide | earnvid.com, vidhide.com | |
| Filemoon / Byse | filemoon.sx, byse*.com, + many mirrors | ✓ |
| Google Drive | drive.google.com | |
| Lulustream | luluvdo.com, lulu.st | |
| Lycoris.cafe | lycoris.cafe | |
| MP4Upload | mp4upload.com | |
| OK.ru | ok.ru | |
| Pixeldrain | pixeldrain.com | |
| Rumble | rumble.com | |
| Savefiles / StreamHG | savefiles.com, bigwarp.io | |
| SendVid | sendvid.com | |
| Sibnet | sibnet.ru | |
| Streamtape | streamtape.com | ✓ |
| StreamUP | strmup.to | |
| Turbovid | turboviplay.com | |
| UPnShare / RPMShare | upns.pro, rpmhub.site | |
| Uqload | uqload.com | ✓ |
| Veev | veev.to | |
| Vidara / Streamix | vidara.so, vidara.to | |
| Vidguard | vidguard.to | |
| Vidnest | vidnest.io | |
| Vidoza | vidoza.net | |
| Vids.st | vids.st | |
| Vidtube | vidtube.one | |
| VK | vk.com, vkvideo.ru | |
| VOE | voe.sx | ✓ |

**Proxy Required** = player streams are IP-bound; extraction must happen from the same IP that will play the stream. Use [MediaFlow Proxy](https://github.com/mhdzumair/mediaflow-proxy) or similar.

## Requirements

```
aiohttp>=3.9
pycryptodome>=3.18
cryptography>=42.0
yarl
```

For the Filemoon/Byse native PoW solver (optional but recommended):
- `gcc` and `libc6-dev` to compile `pow_solver.c` → `pow_solver.so`
- Pre-built `pow_solver.so` (x86_64 Linux) is included in the repo

## Usage

Each player module exposes an async function with signature:

```python
async def get_video_from_<name>_player(
    session: aiohttp.ClientSession,
    url: str,
    is_vip: bool = False
) -> tuple[str | None, str | None, dict | None]:
    """
    Returns: (stream_url, quality, headers_dict) or (None, None, None) on failure
    """
```

Example:

```python
import aiohttp
from players.filemoon import get_video_from_filemoon_player

async def extract():
    async with aiohttp.ClientSession() as session:
        url, quality, headers = await get_video_from_filemoon_player(
            session, "https://bysesukior.com/e/abc123", is_vip=True
        )
        if url:
            print(f"Stream: {url} ({quality})")
```

## Adding to Your Project

### As a Git submodule

```bash
git submodule add https://github.com/skoruppa/docchi-players.git app/players
```

### Configuration

Players expect a `config.py` at your project root with:

```python
class Config:
    PROXIFY_STREAMS = False  # or True
    STREAM_PROXY_URL = ""    # MediaFlow Proxy URL
    STREAM_PROXY_PASSWORD = ""
    FORCE_VIP_PLAYERS = False
```

And `app/utils/common_utils.py` providing:
- `get_random_agent()` → random User-Agent string
- `fetch_resolution_from_m3u8(session, url, headers)` → quality string

### Compiling the PoW solver (Filemoon)

The pre-built `pow_solver.so` works on x86_64 Linux. For other architectures:

```bash
cd app/players
gcc -O3 -shared -fPIC -o pow_solver.so pow_solver.c
```

If the `.so` is unavailable or fails to load, a pure Python fallback is used automatically (~10s vs ~50ms).

## Contributing

Contributions welcome! To add a new player:

1. Create `playername.py` with the standard interface
2. Set `DOMAINS`, `NAMES`, `ENABLED` module-level variables
3. Implement `get_video_from_<name>_player(session, url, is_vip)` 
4. Add to this README

## License

MIT
