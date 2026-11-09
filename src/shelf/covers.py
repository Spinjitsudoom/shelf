"""Album cover lookup, resizing/caching, and accent-color extraction."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

from PIL import Image, ImageOps

from .tags import embedded_art

COVER_SIZES = (160, 320, 640, 1200)
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_PREFERRED = ("cover", "folder", "front", "album", "albumart", "albumartlarge")


def find_folder_image(folder: Path) -> Path | None:
    """Pick the most likely front cover image sitting next to the tracks."""
    try:
        images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    except OSError:
        return None
    if not images:
        return None
    by_stem = {p.stem.lower(): p for p in images}
    for name in _PREFERRED:
        if name in by_stem:
            return by_stem[name]
    for p in images:
        stem = p.stem.lower()
        if "cover" in stem or "front" in stem:
            return p
    # Only trust an arbitrary image when it's the sole one in the folder.
    return images[0] if len(images) == 1 else None


def snap_size(size: int) -> int:
    for s in COVER_SIZES:
        if size <= s:
            return s
    return COVER_SIZES[-1]


def _source(cover_src: str) -> tuple[Path, bool]:
    """cover_src is either 'file:<path>' or 'embedded:<audio path>'."""
    kind, _, path = cover_src.partition(":")
    return Path(path), kind == "embedded"


def _load_source_bytes(cover_src: str) -> bytes | None:
    path, embedded = _source(cover_src)
    if embedded:
        return embedded_art(path)
    try:
        return path.read_bytes()
    except OSError:
        return None


def cache_path(cover_dir: Path, cover_src: str, size: int) -> Path | None:
    path, _ = _source(cover_src)
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return None
    digest = hashlib.sha1(f"{cover_src}|{mtime}".encode()).hexdigest()[:20]
    return cover_dir / f"{digest}_{size}.webp"


def get_cover(cover_dir: Path, cover_src: str, size: int) -> Path | None:
    """Return a cached, resized WebP of the cover, generating it on first request."""
    size = snap_size(size)
    target = cache_path(cover_dir, cover_src, size)
    if target is None:
        return None
    if target.exists():
        return target
    raw = _load_source_bytes(cover_src)
    if not raw:
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return None
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    tmp = target.with_suffix(".tmp")
    img.save(tmp, "WEBP", quality=86, method=4)
    tmp.replace(target)
    return target


def accent_color(image_path: Path) -> str | None:
    """A vivid-but-not-garish color from the cover, for tinting the album page."""
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return None
    img.thumbnail((64, 64))
    pal = img.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = pal.getpalette() or []
    counts = sorted(pal.getcolors() or [], reverse=True)
    best, best_score = None, float("-inf")
    total = sum(c for c, _ in counts) or 1
    for count, idx in counts:
        r, g, b = palette[idx * 3: idx * 3 + 3]
        mx, mn = max(r, g, b), min(r, g, b)
        light = (mx + mn) / 510
        sat = 0 if mx == mn else (mx - mn) / (255 - abs(mx + mn - 255) or 1)
        # Favor colors that are common, saturated, and mid-lightness; near-black and
        # near-white only win when the cover has nothing else to offer.
        score = (count / total) * 0.6 + sat * 0.8 - abs(light - 0.5) * 0.6
        if light < 0.1 or light > 0.92:
            score -= 1.0
        if score > best_score:
            best, best_score = (r, g, b), score
    if best is None:
        return None
    return "#{:02x}{:02x}{:02x}".format(*best)
