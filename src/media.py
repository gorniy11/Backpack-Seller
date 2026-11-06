"""Download and cache item images from Steam's CDN."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from PIL import Image, ImageOps

HOSTS = {"community.steamstatic.com", "community.akamai.steamstatic.com", "community.cloudflare.steamstatic.com",
         "steamcommunity-a.akamaihd.net", "cdn.steamcommunity.com",
         "community.fastly.steamstatic.com"}
MAX_BYTES = 4_000_000


def allowed_image(url):
    try:
        parsed = urlsplit(str(url))
        return (parsed.scheme == "https" and parsed.hostname in HOSTS and parsed.port in (None, 443)
                and not parsed.username and not parsed.password and parsed.path.startswith("/economy/image/"))
    except ValueError:
        return False


def image_png(blob, size=256):
    with Image.open(io.BytesIO(blob)) as source:
        if source.width * source.height > 16_000_000:
            raise ValueError("Image too large")
        picture = ImageOps.contain(source.convert("RGBA"), (size, size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        picture.save(out, format="PNG")
        return out.getvalue()


def load_image(url, cache: Path, session=None):
    if not allowed_image(url):
        raise ValueError("Unsupported image address")
    target = cache / (hashlib.sha256(url.encode()).hexdigest() + ".png")
    if target.is_file() and target.stat().st_size <= MAX_BYTES:
        try:
            return image_png(target.read_bytes())
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    own = session is None
    session = session or requests.Session()
    parsed = urlsplit(url)
    candidates = [url, urlunsplit(parsed._replace(netloc="community.akamai.steamstatic.com")),
                  urlunsplit(parsed._replace(netloc="community.cloudflare.steamstatic.com"))]
    try:
        for candidate in dict.fromkeys(candidates):
            try:
                current = candidate
                for _ in range(4):
                    if not allowed_image(current):
                        raise ValueError("Unsupported image redirect")
                    with session.get(current, timeout=(6, 15), allow_redirects=False, stream=True) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            current = urljoin(current, response.headers.get("Location", ""))
                            continue
                        response.raise_for_status()
                        blob = bytearray()
                        for chunk in response.iter_content(65536):
                            blob.extend(chunk)
                            if len(blob) > MAX_BYTES:
                                raise ValueError("Image too large")
                        data = image_png(bytes(blob))
                        try:
                            cache.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(data)
                        except OSError:
                            pass  # Read-only cache must not hide a downloaded image.
                        return data
            except (requests.RequestException, OSError, ValueError, Image.DecompressionBombError):
                continue
        raise ValueError("Steam image is temporarily unavailable")
    finally:
        if own:
            session.close()
