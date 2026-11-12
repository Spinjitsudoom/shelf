"""Read tags and embedded cover art from audio files.

mutagen handles the common formats quickly; ffprobe/ffmpeg is the fallback for
anything mutagen rejects (e.g. a ``.flac`` file that is really FLAC-in-MP4).
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.flac import Picture
from . import procs

AUDIO_EXTS = {
    ".mp3", ".flac", ".m4a", ".mp4", ".aac", ".alac", ".ogg", ".oga", ".opus",
    ".wav", ".aif", ".aiff", ".wma", ".ape", ".wv",
}

_YEAR = re.compile(r"\d{4}")
_NUM = re.compile(r"\d+")


@dataclass
class TrackInfo:
    title: str
    artist: str
    album_artist: str | None
    album: str | None
    track_no: int | None
    disc_no: int | None
    year: int | None
    genre: str | None
    duration: float
    codec: str
    mime: str
    bitrate: int | None
    sample_rate: int | None
    bits: int | None
    has_art: bool
    lufs: float | None = None  # from ReplayGain / R128 tags, when present
    peak: float | None = None
    extra: dict = field(default_factory=dict)  # the less common tags, see extras()


def _first(value) -> str | None:
    """Tag values come back as lists, frames, tuples or strings depending on format."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    if hasattr(value, "text"):  # ID3 frame
        return _first(value.text)
    text = str(value).strip().strip("\x00")
    return text or None


def _int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, tuple):  # MP4 trkn/disk: (number, total)
        return value[0] or None
    m = _NUM.search(str(value))
    return int(m.group()) if m else None


def _year(value) -> int | None:
    if value is None:
        return None
    m = _YEAR.search(str(value))
    return int(m.group()) if m else None


# ---------- the less common tags ----------
# MusicBrainz ids, composers, ISRCs, labels and the like: not used by Shelf's own screens, but
# Subsonic apps show them (and ListenBrainz matches better with the MusicBrainz ids).
# Each is (name in Vorbis comments / ffprobe, ID3 frame or TXXX description, MP4 atom or
# iTunes freeform name).
_EXTRA = {
    "mbid": (("musicbrainz_trackid", "musicbrainz track id"), ("UFID:http://musicbrainz.org", "TXXX:MusicBrainz Track Id"),
             ("----:com.apple.iTunes:MusicBrainz Track Id",)),
    "album_mbid": (("musicbrainz_albumid", "musicbrainz album id"), ("TXXX:MusicBrainz Album Id",),
                   ("----:com.apple.iTunes:MusicBrainz Album Id",)),
    "artist_mbid": (("musicbrainz_artistid", "musicbrainz artist id"), ("TXXX:MusicBrainz Artist Id",),
                    ("----:com.apple.iTunes:MusicBrainz Artist Id",)),
    "composers": (("composer",), ("TCOM",), ("\xa9wrt",)),
    "isrc": (("isrc", "tsrc"), ("TSRC", "TXXX:ISRC"), ("----:com.apple.iTunes:ISRC",)),
    "comment": (("comment", "description"), ("COMM",), ("\xa9cmt",)),
    "sort": (("titlesort", "title-sort", "title_sort"), ("TSOT",), ("sonm",)),
    "album_sort": (("albumsort", "album-sort", "album_sort"), ("TSOA",), ("soal",)),
    "compilation": (("compilation",), ("TCMP", "TXXX:TCMP"), ("cpil",)),
    "release_types": (("releasetype", "musicbrainz_albumtype", "musicbrainz album type"),
                      ("TXXX:MusicBrainz Album Type", "TXXX:RELEASETYPE"), ("----:com.apple.iTunes:MusicBrainz Album Type",)),
    "labels": (("label", "organization", "publisher"), ("TPUB", "TXXX:LABEL"), ("----:com.apple.iTunes:LABEL", "\xa9pub")),
    "original_year": (("originaldate", "originalyear", "original_year"), ("TDOR", "TORY", "TXXX:originalyear"),
                      ("----:com.apple.iTunes:ORIGINALDATE", "----:com.apple.iTunes:originalyear")),
    "explicit": (("itunesadvisory",), ("TXXX:ITUNESADVISORY",), ("rtng",)),
    "moods": (("mood",), ("TMOO",), ("----:com.apple.iTunes:MOOD",)),
}
_LISTS = {"composers", "isrc", "release_types", "labels", "moods"}


def _strings(value) -> list[str]:
    """Every text in a tag value, whatever shape the format gives it."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    if hasattr(value, "text") and not isinstance(value, str):  # ID3 frame
        return _strings(value.text)
    if hasattr(value, "data") and isinstance(getattr(value, "data"), bytes) and not isinstance(value, bytes):  # UFID
        value = value.data
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    if isinstance(value, bool):
        return ["1" if value else "0"]
    text = str(value).strip().strip("\x00").strip()
    return [text] if text else []


def _flat_tags(f, family: str | None) -> dict[str, list[str]]:
    """A file's tags as {lowercase name: [texts]}, with ID3 TXXX and MP4 freeform names spelled
    like _EXTRA's."""
    tags = f.tags
    out: dict[str, list[str]] = {}
    if tags is None or family is None:
        return out
    try:
        if family == "id3":
            for frame in tags.values():
                fid = frame.FrameID
                if fid == "TXXX":
                    key = f"txxx:{frame.desc}".lower()
                elif fid == "UFID":
                    key = f"ufid:{frame.owner}".lower()
                elif fid == "COMM":
                    if frame.desc and frame.desc.lower() not in ("", "comment", "description"):
                        continue  # iTunNORM and friends
                    key = "comm"
                else:
                    key = fid.lower()
                out.setdefault(key, []).extend(_strings(frame))
        else:
            for k, v in tags.items():
                out.setdefault(str(k).lower(), []).extend(_strings(v))
    except Exception:
        return {}
    return out


def extras_from(flat: dict[str, list[str]], family: str, channels: int | None = None) -> dict:
    col = {"vorbis": 0, "ape": 0, "asf": 0, "ffprobe": 0, "id3": 1, "mp4": 2}.get(family, 0)
    out: dict = {}
    for name, spellings in _EXTRA.items():
        values: list[str] = []
        for key in spellings[col]:
            values += flat.get(key.lower(), [])
            if values:
                break
        if name in _LISTS:
            split = [p.strip() for v in values for p in re.split(r"\s*(?:;|\x00|/(?=\s)|\s/)\s*", v) if p.strip()]
            seen: list[str] = []
            for v in split:
                if v.lower() not in {s.lower() for s in seen}:
                    seen.append(v)
            if seen:
                out[name] = seen[:20]
        elif values:
            out[name] = values[0][:500]
    if "release_types" in out:
        out["release_types"] = [t.lower() for t in out["release_types"]]
    if "original_year" in out:
        y = _year(out["original_year"])
        out.pop("original_year")
        if y:
            out["original_year"] = y
    if "compilation" in out:
        out["compilation"] = out["compilation"].strip().lower() in ("1", "true", "yes")
        if not out["compilation"]:
            out.pop("compilation")
    if "explicit" in out:  # iTunes advisory: 1 or 4 explicit, 2 clean
        v = out.pop("explicit").strip()
        if v in ("1", "4"):
            out["explicit"] = "explicit"
        elif v == "2":
            out["explicit"] = "clean"
    for k in ("mbid", "album_mbid", "artist_mbid"):
        if k in out and not re.fullmatch(r"[0-9a-fA-F-]{36}", out[k].strip()):
            out.pop(k)
    if channels:
        out["channels"] = int(channels)
    return out


# Per-format tag names for: title, artist, albumartist, album, track, disc, date, genre
_KEYS = {
    "id3": ("TIT2", "TPE1", "TPE2", "TALB", "TRCK", "TPOS", "TDRC", "TCON"),
    "vorbis": ("title", "artist", "albumartist", "album", "tracknumber", "discnumber", "date", "genre"),
    "mp4": ("\xa9nam", "\xa9ART", "aART", "\xa9alb", "trkn", "disk", "\xa9day", "\xa9gen"),
    "asf": ("Title", "Author", "WM/AlbumArtist", "WM/AlbumTitle", "WM/TrackNumber", "WM/PartOfSet", "WM/Year", "WM/Genre"),
    "ape": ("Title", "Artist", "Album Artist", "Album", "Track", "Disc", "Year", "Genre"),
}

_MIME = {
    "MP3": ("mp3", "audio/mpeg"),
    "FLAC": ("flac", "audio/flac"),
    "OggVorbis": ("vorbis", "audio/ogg"),
    "OggOpus": ("opus", "audio/ogg"),
    "OggFLAC": ("flac", "audio/ogg"),
    "WAVE": ("pcm", "audio/wav"),
    "AIFF": ("pcm", "audio/aiff"),
    "ASF": ("wma", "audio/x-ms-wma"),
    "MonkeysAudio": ("ape", "audio/x-ape"),
    "WavPack": ("wavpack", "audio/x-wavpack"),
    "AAC": ("aac", "audio/aac"),
}


def _tag_family(f) -> str | None:
    kind = type(f).__name__
    tags = f.tags
    if tags is None:
        return None
    tname = type(tags).__name__
    if tname in ("ID3", "_WaveID3", "_IFFID3"):
        return "id3"
    if tname == "MP4Tags":
        return "mp4"
    if tname == "ASFTags":
        return "asf"
    if tname == "APEv2":
        return "ape"
    if "Vorbis" in tname or kind.startswith("Ogg") or kind == "FLAC":
        return "vorbis"
    return None


def _get(tags, family: str, idx: int):
    key = _KEYS[family][idx]
    if family == "vorbis":
        val = tags.get(key)
        if val is None and key == "albumartist":
            val = tags.get("album artist") or tags.get("album_artist")
        return val
    try:
        return tags.get(key) if hasattr(tags, "get") else tags[key]
    except (KeyError, ValueError):
        return None


def _mutagen_has_art(f, family: str | None) -> bool:
    if getattr(f, "pictures", None):  # FLAC
        return True
    tags = f.tags
    if tags is None:
        return False
    if family == "id3":
        return bool(tags.getall("APIC"))
    if family == "mp4":
        return bool(tags.get("covr"))
    if family == "vorbis":
        return bool(tags.get("metadata_block_picture"))
    if family == "asf":
        return bool(tags.get("WM/Picture"))
    if family == "ape":
        return "Cover Art (Front)" in tags
    return False


_DB = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _rg_to_loudness(gain, peak, r128=None) -> tuple[float | None, float | None]:
    """ReplayGain 2 gains are relative to -18 LUFS; Opus R128 gains (Q7.8) to -23 LUFS."""
    lufs = pk = None
    if r128 is not None:
        m = _DB.search(str(r128))
        if m:
            lufs = -23.0 - float(m.group()) / 256
    elif gain is not None:
        m = _DB.search(str(gain))
        if m:
            lufs = -18.0 - float(m.group())
    if peak is not None:
        m = _DB.search(str(peak))
        if m and float(m.group()) > 0:
            import math
            pk = 20 * math.log10(float(m.group()))
    return lufs, pk


def _mutagen_replaygain(f, family: str | None) -> tuple[float | None, float | None]:
    tags = f.tags
    if tags is None or family is None:
        return None, None
    try:
        if family == "vorbis":
            return _rg_to_loudness(_first(tags.get("replaygain_track_gain")), _first(tags.get("replaygain_track_peak")),
                                   _first(tags.get("r128_track_gain")))
        if family == "id3":
            txxx = {fr.desc.lower(): fr.text[0] for fr in tags.getall("TXXX") if fr.text}
            return _rg_to_loudness(txxx.get("replaygain_track_gain"), txxx.get("replaygain_track_peak"))
        if family == "mp4":
            get = lambda k: bytes(tags[k][0]).decode(errors="ignore") if k in tags else None  # noqa: E731
            return _rg_to_loudness(get("----:com.apple.iTunes:replaygain_track_gain"),
                                   get("----:com.apple.iTunes:replaygain_track_peak"))
        if family == "ape":
            return _rg_to_loudness(_first(tags.get("REPLAYGAIN_TRACK_GAIN")), _first(tags.get("REPLAYGAIN_TRACK_PEAK")))
    except Exception:
        pass
    return None, None


def _read_mutagen(path: Path) -> TrackInfo | None:
    f = mutagen.File(path)
    if f is None or f.info is None:
        return None
    family = _tag_family(f)
    tags = f.tags

    def g(i):
        return _get(tags, family, i) if family else None

    kind = type(f).__name__
    codec, mime = _MIME.get(kind, (kind.lower(), "application/octet-stream"))
    if kind == "MP4":
        raw_codec = getattr(f.info, "codec", "") or ""
        codec = {"mp4a.40.2": "aac", "mp4a.40.5": "aac", "alac": "alac", "flac": "flac"}.get(
            raw_codec.lower(), raw_codec or "aac"
        )
        mime = "audio/mp4"

    title = _first(g(0)) or path.stem
    lufs, peak = _mutagen_replaygain(f, family)
    return TrackInfo(
        title=title,
        artist=_first(g(1)) or "Unknown Artist",
        album_artist=_first(g(2)),
        album=_first(g(3)),
        track_no=_int(g(4)[0] if family == "mp4" and g(4) else _first(g(4))),
        disc_no=_int(g(5)[0] if family == "mp4" and g(5) else _first(g(5))),
        year=_year(_first(g(6))),
        genre=_first(g(7)),
        duration=float(getattr(f.info, "length", 0) or 0),
        codec=codec,
        mime=mime,
        bitrate=getattr(f.info, "bitrate", None) or None,
        sample_rate=getattr(f.info, "sample_rate", None) or None,
        bits=getattr(f.info, "bits_per_sample", None) or None,
        has_art=_mutagen_has_art(f, family),
        lufs=lufs,
        peak=peak,
        extra=extras_from(_flat_tags(f, family), family or "", getattr(f.info, "channels", None)),
    )


_FORMAT_MIME = {
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "aiff": "audio/aiff",
    "mov,mp4,m4a,3gp,3g2,mj2": "audio/mp4",
    "asf": "audio/x-ms-wma",
}


def _read_ffprobe(path: Path) -> TrackInfo | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=30, check=True, **procs.no_window(),
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    data = json.loads(out or b"{}")
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio is None:
        return None
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    tags.update({k.lower(): v for k, v in (audio.get("tags") or {}).items() if k.lower() not in tags})
    has_art = any(
        s.get("codec_type") == "video" and (s.get("disposition") or {}).get("attached_pic")
        for s in streams
    )
    return TrackInfo(
        title=tags.get("title") or path.stem,
        artist=tags.get("artist") or "Unknown Artist",
        album_artist=tags.get("album_artist") or tags.get("albumartist"),
        album=tags.get("album"),
        track_no=_int(tags.get("track")),
        disc_no=_int(tags.get("disc")),
        year=_year(tags.get("date") or tags.get("year")),
        genre=tags.get("genre"),
        duration=float(fmt.get("duration") or audio.get("duration") or 0),
        codec=audio.get("codec_name", "unknown"),
        mime=_FORMAT_MIME.get(fmt.get("format_name", ""), "application/octet-stream"),
        bitrate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        sample_rate=int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        bits=_int(audio.get("bits_per_raw_sample") or audio.get("bits_per_sample")) or None,
        has_art=has_art,
        extra=extras_from({k: [str(v)] for k, v in tags.items()}, "ffprobe", _int(audio.get("channels"))),
        **dict(zip(("lufs", "peak"), _rg_to_loudness(
            tags.get("replaygain_track_gain"), tags.get("replaygain_track_peak"), tags.get("r128_track_gain")))),
    )


def read_tags(path: Path) -> TrackInfo | None:
    try:
        info = _read_mutagen(path)
    except Exception:
        info = None
    return info or _read_ffprobe(path)


def embedded_art(path: Path) -> bytes | None:
    """Return the front cover (or first picture) embedded in an audio file."""
    try:
        f = mutagen.File(path)
    except Exception:
        f = None
    if f is not None:
        try:
            data = _mutagen_art(f)
            if data:
                return data
        except Exception:
            pass
    try:
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-an", "-map", "0:v:0",
             "-c:v", "copy", "-frames:v", "1", "-f", "image2pipe", "-"],
            capture_output=True, timeout=30, **procs.no_window(),
        )
        return out.stdout or None
    except (subprocess.SubprocessError, OSError):
        return None


def _mutagen_art(f) -> bytes | None:
    pics = getattr(f, "pictures", None)
    if pics:
        front = next((p for p in pics if p.type == 3), pics[0])
        return front.data
    tags = f.tags
    if tags is None:
        return None
    family = _tag_family(f)
    if family == "id3":
        frames = tags.getall("APIC")
        if frames:
            front = next((p for p in frames if p.type == 3), frames[0])
            return front.data
    elif family == "mp4":
        covr = tags.get("covr")
        if covr:
            return bytes(covr[0])
    elif family == "vorbis":
        blocks = tags.get("metadata_block_picture")
        if blocks:
            return Picture(base64.b64decode(blocks[0])).data
    elif family == "asf":
        pics = tags.get("WM/Picture")
        if pics:
            raw = pics[0].value
            # ASF picture: type(1) + size(4) + mime(utf16z) + desc(utf16z) + data
            i = 5
            for _ in range(2):
                while raw[i:i + 2] != b"\x00\x00":
                    i += 2
                i += 2
            return raw[i:]
    elif family == "ape":
        item = tags.get("Cover Art (Front)")
        if item:
            raw = item.value
            return raw[raw.index(b"\x00") + 1:]
    return None


def embedded_lyrics(path: Path) -> str | None:
    """Lyrics stored in the file's tags, as LRC text when they're timed, else plain text."""
    try:
        f = mutagen.File(path)
    except Exception:
        return None
    if f is None or f.tags is None:
        return None
    tags = f.tags
    family = _tag_family(f)
    try:
        if family == "id3":
            for frame in tags.getall("SYLT"):
                # Timed lyrics in milliseconds (format 2); rebuild them as LRC.
                if frame.format == 2 and frame.text:
                    return "\n".join(
                        f"[{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}]{text.strip()}" for text, ms in frame.text
                    )
            texts = [str(fr.text) for fr in tags.getall("USLT") if str(fr.text).strip()]
            return texts[0] if texts else None
        if family == "vorbis":
            for key in ("syncedlyrics", "lyrics", "unsyncedlyrics", "unsynced lyrics"):
                val = tags.get(key)
                if val and str(val[0]).strip():
                    return str(val[0])
        elif family == "mp4":
            val = tags.get("\xa9lyr")
            return str(val[0]) if val else None
        elif family == "asf":
            val = tags.get("WM/Lyrics")
            return str(val[0].value) if val else None
        elif family == "ape":
            val = tags.get("Lyrics")
            return str(val.value) if val else None
    except Exception:
        return None
    return None
