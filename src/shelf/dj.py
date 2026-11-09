"""DJ: a radio host for your own shelf.

It plays your music in short segments (recent favourites, throwbacks, an artist spotlight,
deep cuts, something you've never played), and before each one it talks over the start of
the first song: who it is, why it's on, a fact about the artist.

Three parts:
- Picking the songs: from each person's plays and likes, with "sounds like" (see mixes.py).
- Writing the line: a language model (Gemini by default; Claude or a local Ollama model also
  work) gets the facts and writes a sentence or three. With no model set up, or if it fails,
  built-in lines are used, so the DJ always talks.
- Saying it: Kokoro, an open text-to-speech model, run on this server in its own helper
  process (see tts_worker.py). Spoken lines are cached.

Sent to the language model: your first name, the time of day, and the songs' titles, artists,
albums and years, with how often you've played them. Nothing is sent without a model set up.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("shelf.dj")

# Kokoro's voices, most natural first (Heart and Bella are its best by a distance).
VOICES = {
    "af_heart": "Heart: warm, the most natural", "af_bella": "Bella: bright and lively",
    "bf_emma": "Emma: British", "af_nicole": "Nicole: soft, close to the mic",
    "am_michael": "Michael: American man", "am_fenrir": "Fenrir: deeper American man",
    "am_puck": "Puck: playful American man", "bm_george": "George: British man",
}
# Gemini's voices (cloud, with the Gemini key): told to sound like a relaxed radio DJ.
GEMINI_VOICES = {
    "gemini:Sulafat": "Sulafat (Gemini): warm", "gemini:Puck": "Puck (Gemini): upbeat",
    "gemini:Charon": "Charon (Gemini): deep and smooth", "gemini:Achird": "Achird (Gemini): friendly",
    "gemini:Aoede": "Aoede (Gemini): breezy", "gemini:Fenrir": "Fenrir (Gemini): excitable",
    "gemini:Zephyr": "Zephyr (Gemini): bright",
}
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
# Chatterbox (natural, on the graphics card): its own voice, or the sound of a Kokoro voice with
# Chatterbox's human delivery (from a short sample of that voice).
NATURAL_VOICES = {
    "natural:am_fenrir": "Fenrir, natural: deep American man", "natural:am_michael": "Michael, natural: American man",
    "natural:bm_george": "George, natural: British man", "natural:af_heart": "Heart, natural: warm American woman",
    "natural:bf_emma": "Emma, natural: British woman", "natural:default": "Chatterbox's own voice: American woman",
}
REF_TEXT = ("Hey, good to have you here. I've lined up some great music for you tonight, a few old favourites "
            "and something you haven't heard yet. So sit back, turn it up a little, and let's get going.")
DEFAULT_VOICE = "af_heart"

# Names text-to-speech gets wrong, and spellings that sound right (the text shown is unchanged).
SAY = {"yungblud": "Youngblood", "måneskin": "Maaneskin", "maneskin": "Maaneskin", "ranieri": "Rahn-yeh-ree"}
KEEP_CAPS = {"AC/DC", "ABBA", "NASA", "UFO", "KISS", "MGMT", "HAIM", "AURORA"}


def speakable_title(title: str) -> str:
    """"Snuff (Radio Edit)" or "Paranoid - 2009 Remaster" as a host would say it."""
    t = re.sub(r"[\(\[](\w{1,3})[\)\]](?=\w)", r"\1", title or "")  # "(O)rdinary" is "Ordinary"
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", t)
    t = re.sub(r"\s+-\s+.*(remaster|edit|version|live|mix|mono|stereo|from|demo|bonus).*$", "", t, flags=re.I)
    return t.strip() or title


def for_speech(text: str, extra: dict[str, str] | None = None) -> str:
    """The words as the voice should hear them: names respelled to sound right, and names in
    capitals read as words rather than spelled out."""
    rules = {**SAY, **{k.strip().lower(): v.strip() for k, v in (extra or {}).items() if k.strip() and v.strip()}}
    for k in sorted(rules, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(k)}(?!\w)", rules[k], text, flags=re.I)
    return re.sub(r"\b[A-Z]{4,}\b", lambda m: m.group(0) if m.group(0) in KEEP_CAPS else m.group(0).capitalize(), text)


def parse_say(text: str) -> dict[str, str]:
    """Lines like "Yungblud = Youngblood" (the admin's pronunciation list)."""
    out = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


def gemini_tts(key: str, voice: str, text: str, out_wav: Path, model: str | None = None) -> float:
    """Speak with one of Gemini's voices; returns seconds. Raises on failure."""
    import base64
    r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model or GEMINI_TTS_MODEL}:generateContent",
              {"contents": [{"parts": [{"text": "Say this like a warm, relaxed radio DJ talking to one listener over "
                                                  f"the start of a song, natural and unhurried: {text}"}]}],
               "generationConfig": {"responseModalities": ["AUDIO"],
                                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}},
              {"x-goog-api-key": key}, timeout=90)
    part = r["candidates"][0]["content"]["parts"][0]["inlineData"]
    pcm = base64.b64decode(part["data"])
    rate = int(re.search(r"rate=(\d+)", part.get("mimeType", "")).group(1)) if "rate=" in part.get("mimeType", "") else 24000
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-", str(out_wav)],
                   input=pcm, check=True, capture_output=True, timeout=60)
    return round(len(pcm) / 2 / rate, 2)
PROVIDERS = {"builtin": "Built in (this server)", "gemini": "Gemini", "anthropic": "Claude",
             "ollama": "Ollama", "none": "Simple lines only (no AI)"}
DEFAULT_MODELS = {"gemini": "gemini-flash-latest", "anthropic": "claude-haiku-5-5", "ollama": "qwen3:8b"}


# ---------- the voice ----------

# Radio-style processing on the voice: rumble off, a little chest and presence, compressed so it
# sits up front over the music, then evened out in loudness.
BROADCAST = ("highpass=f=75,equalizer=f=180:t=q:w=1.1:g=2,equalizer=f=3200:t=q:w=1.4:g=3,"
             "equalizer=f=7500:t=q:w=2:g=-1.5,acompressor=threshold=-22dB:ratio=3.5:attack=4:release=140:makeup=3,"
             "loudnorm=I=-15:TP=-1.5")


class Voice:
    """Kokoro, kept loaded in a helper process; lines become small AAC files, cached."""

    def __init__(self, tts_dir: Path, cache_dir: Path):
        self.tts_dir = tts_dir
        self.cache_dir = cache_dir
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def python(self) -> Path:
        return self.tts_dir / "venv" / "bin" / "python"

    @property
    def available(self) -> bool:
        return self.python.exists() and (self.tts_dir / "kokoro-v1.0.onnx").exists() and (self.tts_dir / "voices-v1.0.bin").exists()

    def _start(self) -> None:
        worker = Path(__file__).with_name("tts_worker.py")
        self._proc = subprocess.Popen(
            [str(self.python), str(worker), str(self.tts_dir / "kokoro-v1.0.onnx"), str(self.tts_dir / "voices-v1.0.bin")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        ready = self._proc.stdout.readline()
        if not ready or not json.loads(ready).get("ready"):
            raise OSError("The DJ's voice didn't start")

    def clip_id(self, text: str, voice: str, speed: float) -> str:
        extra = f"|{self.expressiveness}" if voice.startswith("natural:") else ""
        return hashlib.sha1(f"v3|{voice}|{speed}{extra}|{text}".encode()).hexdigest()[:20]

    def path(self, clip: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{20}", clip):
            return None
        p = self.cache_dir / f"{clip}.m4a"
        return p if p.exists() else None

    natural: "Chatterbox | None" = None  # set by app.py
    expressiveness: float = 0.6

    def reference(self, kokoro_voice: str) -> Path:
        """A 10-second sample of a Kokoro voice, for Chatterbox to take on (made once)."""
        refs = self.cache_dir.parent / "dj-voices"
        refs.mkdir(parents=True, exist_ok=True)
        ref = refs / f"{kokoro_voice}.wav"
        if not ref.exists():
            with self._lock:
                if self._proc is None or self._proc.poll() is not None:
                    self._start()
                self._proc.stdin.write(json.dumps({"chunks": phrasing(REF_TEXT), "voice": kokoro_voice, "out": str(ref)}) + "\n")
                self._proc.stdin.flush()
                if not json.loads(self._proc.stdout.readline() or "{}").get("ok"):
                    ref.unlink(missing_ok=True)
                    raise OSError("Couldn't make the voice sample")
        return ref

    def dialogue(self, turns: list[tuple[str, str]], voice_a: str, voice_b: str, speed: float = 1.0,
                 gemini_key: str | None = None) -> tuple[str, float]:
        """Two hosts' turns, each in its own voice, joined into one clip with short gaps."""
        clip = hashlib.sha1(json.dumps([turns, voice_a, voice_b, speed, self.expressiveness]).encode()).hexdigest()[:20]
        out = self.cache_dir / f"{clip}.m4a"
        meta = self.cache_dir / f"{clip}.json"
        if out.exists() and meta.exists():
            return clip, json.loads(meta.read_text())["seconds"]
        parts = [self.path(self.speak(line, voice_b if who == "B" else voice_a, speed, gemini_key)[0]) for who, line in turns]
        inputs, filt = [], []
        for i, p in enumerate(parts):
            inputs += ["-i", str(p)]
            filt.append(f"[{i}:a]apad=pad_dur=0.22[a{i}]")
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-filter_complex",
               ";".join(filt) + ";" + "".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1",
               "-c:a", "aac", "-b:a", "96k", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        seconds = sum(json.loads((self.cache_dir / f"{p.stem}.json").read_text())["seconds"] + 0.22 for p in parts)
        meta.write_text(json.dumps({"seconds": round(seconds, 2), "text": " / ".join(l for _, l in turns)}))
        return clip, round(seconds, 2)

    def speak(self, text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0, gemini_key: str | None = None) -> tuple[str, float]:
        """(clip id, seconds) for a spoken line. A Gemini voice needs the key; without it (or if
        Gemini fails) Kokoro speaks instead."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        clip = self.clip_id(text, voice, speed)
        out = self.cache_dir / f"{clip}.m4a"
        meta = self.cache_dir / f"{clip}.json"
        if out.exists() and meta.exists():
            return clip, json.loads(meta.read_text())["seconds"]
        wav = self.cache_dir / f"{clip}.wav"
        if voice.startswith("natural:"):
            base = voice.split(":", 1)[1]
            if self.natural and self.natural.usable():
                try:
                    ref = None if base == "default" else self.reference(base)
                    seconds = self.natural.speak(text, ref, self.expressiveness, wav)
                    return self._finish(clip, wav, seconds, text)
                except (OSError, ValueError, subprocess.SubprocessError) as e:
                    log.warning("The natural voice failed (%s); Kokoro is speaking instead", e)
            voice = base if base in VOICES else DEFAULT_VOICE
        if voice.startswith("gemini:"):
            if gemini_key:
                try:
                    return self._finish(clip, wav, gemini_tts(gemini_key, voice.split(":", 1)[1], text, wav), text)
                except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError, subprocess.SubprocessError) as e:
                    log.warning("Gemini's voice failed (%s); Kokoro is speaking instead", e)
            voice = DEFAULT_VOICE
        with self._lock:
            for attempt in range(2):
                try:
                    if self._proc is None or self._proc.poll() is not None:
                        self._start()
                    self._proc.stdin.write(json.dumps({"chunks": phrasing(text, speed), "voice": voice, "out": str(wav)}) + "\n")
                    self._proc.stdin.flush()
                    res = json.loads(self._proc.stdout.readline() or "{}")
                    break
                except (OSError, ValueError, BrokenPipeError):
                    self._proc = None
                    if attempt:
                        raise
            if not res.get("ok"):
                raise OSError(res.get("error") or "The DJ's voice failed")
        return self._finish(clip, wav, res["seconds"], text)

    def _finish(self, clip: str, wav: Path, seconds: float, text: str) -> tuple[str, float]:
        out = self.cache_dir / f"{clip}.m4a"
        meta = self.cache_dir / f"{clip}.json"
        # Even loudness, so the DJ sits right over the music; AAC plays everywhere.
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-af", BROADCAST,
                        "-ar", "44100", "-c:a", "aac", "-b:a", "96k", str(out)], check=True, capture_output=True, timeout=60)
        wav.unlink(missing_ok=True)
        meta.write_text(json.dumps({"seconds": seconds, "text": text}))
        return clip, seconds

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


def phrasing(text: str, speed: float = 1.0) -> list[dict]:
    """A line as a person says it: sentence by sentence, a touch quicker into it and settling at
    the end, with a breath of a pause between sentences (a little longer after a question),
    rather than one flat, even run."""
    import random as _r
    text = re.sub(r"\s+[-–—]\s+", ", ", text.strip())
    sentences = [x.strip() for x in re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", text) if x.strip()]
    if not sentences:
        return [{"text": text, "speed": speed, "pause": 0}]
    out = []
    for i, s in enumerate(sentences):
        lift = 1.05 if i == 0 and len(sentences) > 1 else 0.97 if i == len(sentences) - 1 and len(sentences) > 1 else 1.0
        lift *= 1 + _r.uniform(-0.02, 0.02)
        pause = 0 if i == len(sentences) - 1 else (0.36 if s.endswith("?") else _r.uniform(0.2, 0.32))
        out.append({"text": s, "speed": round(speed * lift, 3), "pause": round(pause, 2)})
    return out


# ---------- the words ----------

PERSONA = (
    "You are the host of Shelf Radio, a personal station that plays one listener's own music collection. "
    "You sound like a real radio DJ: warm, quick, a bit of personality, talking to one listener you know well. "
    "Speak to them directly, as \"you\" (never \"he\", \"she\" or \"they\"). "
    "Do what radio hosts do: back-announce what just played, set up what's next, now and then give the time, "
    "tease what's coming later, or drop the station name (\"Shelf Radio\"), but never all of these at once. "
    "Talk the way people actually talk: contractions, a relaxed rhythm, now and then an easy opener like "
    "\"Alright\" or \"So\", and don't start every break the same way. "
    "Write only the words to be spoken, keeping to the word budget you're given, so you finish as the "
    "vocals come in. No emojis, hashtags, stage directions, quotation marks or lists. Say numbers and years "
    "as a host would (\"nineteen seventy\", \"twenty past nine\"). Don't invent facts beyond the ones given. "
    "End by naming the next song and its artist, unless told otherwise."
)


def words_for(seconds: float) -> int:
    """How many words fit in so many seconds of relaxed radio talk."""
    return max(8, min(55, round(seconds * 2.6)))


def _post(url: str, body: dict, headers: dict, timeout: float = 25) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# The built-in writer (local_llm.LocalLLM) and which of its models to use; set by app.py.
local_writer = None


def write(provider: str, key: str | None, model: str | None, system: str, prompt: str,
          json_mode: bool = False, max_tokens: int = 220, schema: dict | None = None) -> str | None:
    """The language model's raw answer, or None (no model set up, or it failed). With
    `json_mode`, asks for JSON. Thinking is turned off where a model has it: a line of radio
    talk doesn't need it, and it costs tokens and time."""
    model = model or DEFAULT_MODELS.get(provider)
    try:
        if provider == "builtin":
            if local_writer is None or not local_writer.installed():
                return None
            choice = model if model in local_writer.installed() else local_writer.installed()[0]
            return local_writer.chat(choice, system, prompt, max_tokens=max_tokens, json_mode=json_mode, schema=schema)
        if provider == "gemini" and key:
            config = {"temperature": 0.9, "maxOutputTokens": max_tokens + 200}
            if json_mode:
                config["responseMimeType"] = "application/json"
            body = {"systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                r = _post(url, {**body, "generationConfig": {**config, "thinkingConfig": {"thinkingBudget": 0}}},
                          {"x-goog-api-key": key})
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    raise
                r = _post(url, body, {"x-goog-api-key": key})  # a model that can't turn thinking off
            return "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"] if not p.get("thought"))
        if provider == "anthropic" and key:
            r = _post("https://api.anthropic.com/v1/messages",
                      {"model": model, "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": prompt}]},
                      {"x-api-key": key, "anthropic-version": "2023-06-01"})
            return "".join(b.get("text", "") for b in r["content"] if b.get("type") == "text")
        if provider == "ollama":
            body = {"model": model, "stream": False, "think": False,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
            if schema or json_mode:
                body["format"] = schema or "json"
            return _post(f"{key or 'http://localhost:11434'}/api/chat", body, {}, timeout=90)["message"]["content"]
        return None
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as e:
        log.warning("The DJ's writer (%s) failed: %s", provider, e)
        return None


def write_line(provider: str, key: str | None, model: str | None, prompt: str) -> str | None:
    """One line of talk, cleaned up, or None."""
    return clean(write(provider, key, model, PERSONA, prompt))


def _json(text: str | None):
    """JSON from a model's answer, tolerating code fences and chatter around it."""
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"[\[{].*[\]}]", text, flags=re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


def clean(text: str) -> str | None:
    """Spoken words only: no thinking, markdown, quotes or emojis; at most about 60 words."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"[*_#`\"“”]", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if len(words) > 60:
        text = " ".join(words[:60]).rsplit(".", 1)[0] + "."
    return text or None


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    return "evening" if 17 <= hour < 22 else "night"


def year_words(y: int | None) -> str:
    if not y:
        return ""
    if 2000 <= y <= 2009:
        return f"two thousand {['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'][y - 2000]}".strip()
    return f"{y // 100} {y % 100:02d}" if y % 100 >= 10 else f"{y // 100} oh {y % 100}"


def _song(t: dict) -> str:
    return f"{speakable_title(t['title'])} by {t['artist']}"


def fallback_line(kind: str, name: str, hour: int, prev: dict | None, nxt: dict, seg: dict | None) -> str:
    """Built-in lines, for when there's no language model (or it's down)."""
    song = _song(nxt)
    back = f"That was {_song(prev)}." if prev else ""
    if nxt.get("rank"):  # the countdown
        return f"{back} At number {nxt['rank']} this week, {song}.".strip()
    if kind == "request":
        return random.choice([f"You asked, I've got you. Here's {song}.", f"Request taken, {name}. Coming right up, {song}.",
                              f"Good call, {name}. Here's {song}."])
    if kind == "link":
        return random.choice([
            f"{back} Here's {song}.", f"{back} Keeping it going with {song}.",
            f"{back} Next up on Shelf Radio, {song}.", f"{back} Stay with me, this is {song}.",
        ]).strip()
    theme = (seg or {}).get("theme")
    intro = {
        "favourites": [f"Some of your recent favourites now, starting with {song}.", f"Here's what you've had on repeat lately. {song}."],
        "throwback": [f"Time for a throwback, something you used to play a lot. {song}.", f"Remember this one? It's been a while. {song}."],
        "discover": [f"Now something from your shelf you've never actually played. I think you'll like it. {song}.",
                     f"Let's try something new to you, picked to sound like your favourites. {song}."],
        "spotlight": [f"Let's spend a few songs with {nxt['artist']}. Starting with {speakable_title(nxt['title'])}.",
                      f"Spotlight on {nxt['artist']} for a bit. Here's {speakable_title(nxt['title'])}."],
        "deep": [f"Some deeper cuts from albums you love. Here's {song}.", f"Going a little deeper now. {song}."],
    }.get(theme, [f"Up next, {song}."])
    if kind == "open":
        greet = random.choice([f"Hey {name}, you're listening to Shelf Radio.", f"Good {part_of_day(hour)}, {name}. This is Shelf Radio.",
                               f"{name}, welcome back to Shelf Radio."])
        return f"{greet} {random.choice(intro)}"
    return f"{back} {random.choice(intro)}".strip()


def prompt_for(kind: str, name: str, when: str, prev: dict | None, nxt: dict, seg: dict | None,
               facts_prev: str | None, facts_next: str | None, about: str | None, friend: str | None,
               seconds: float) -> str:
    """What the language model is told for one break."""
    lines = [f"Listener's first name: {name}.", f"Local time: {when}." if when else ""]
    if kind == "open":
        lines.append("This is the very start of the show: say hello and introduce the station, then the first song.")
    elif kind == "break":
        lines.append("A short break between sets: back-announce the song that just finished, then introduce the next set.")
    else:
        lines.append("A quick link between two songs: one or two short sentences.")
    if prev:
        lines.append(f"Just played: {_song(prev)}" + (f", from {speakable_title(prev['album'])}" if prev.get("album") else "") + ".")
        if facts_prev:
            lines.append(facts_prev)
    if seg and kind != "link":
        lines.append(f"The next set: {seg['brief']}")
        if seg.get("why"):
            lines.append(seg["why"])
        later = seg["tracks"][1:4]
        if later:
            lines.append("Later in this set (you may tease one): " + "; ".join(_song(x) for x in later) + ".")
    lines.append(f"Next song: {_song(nxt)}, from the album {speakable_title(nxt.get('album') or '')}"
                 + (f" ({nxt['year']})" if nxt.get("year") else "") + ".")
    if facts_next:
        lines.append(facts_next)
    if about:
        lines.append(f"About {nxt['artist']} (from Wikipedia; use at most one detail, only if it fits): {about[:500]}")
    if friend:
        lines.append(f"From Friend activity (a shout-out is welcome, not required): {friend}")
    lines.append(f"Word budget: at most {words_for(seconds)} words; you're talking over the song's intro and should "
                 "finish as the singing starts.")
    return "\n".join(x for x in lines if x)


# ---------- a whole set at once ----------

EXAMPLES = """How it sounds (examples of the style only; never reuse their words, and only give a time when you're told it):
- Before a set: "That was Paranoid, Sabbath at full tilt. Let's take it down a notch with a few you haven't had on in a while, starting with Changes."
- Before a set: "This is Shelf Radio. Three from Måneskin coming up, and yes, Beggin' is one of them. First, Zitti e buoni."
- Between songs: "Ozzy and the boys, there. Keeping the riffs coming, this is Snuff by Slipknot."
- Between songs: "That one never gets old. Here's I Cry 2 from Yungblud."
"""
# The same opening for every request, so a local model can keep it loaded between lines.
SET_SYSTEM = PERSONA + "\n\n" + EXAMPLES

_NUM = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"]


def time_words(hour: int, minute: int) -> str:
    """9:20 pm as a host says it: "twenty past nine in the evening" (to the nearest five minutes)."""
    m = int(round(minute / 5) * 5)
    h = hour + (1 if m > 30 else 0)
    if m == 60:
        m = 0
    name = _NUM[h % 12]
    near = {0: f"{name} o'clock", 15: f"quarter past {name}", 30: f"half past {name}", 45: f"quarter to {name}"}.get(m)
    if not near:
        words = {5: "five", 10: "ten", 20: "twenty", 25: "twenty-five", 35: "twenty-five", 40: "twenty", 50: "ten", 55: "five"}[m]
        near = f"{words} past {name}" if m < 30 else f"{words} to {name}"
    return f"{near} in the {part_of_day(hour % 24)}" if part_of_day(hour % 24) != "night" else f"{near} at night"


def link_positions(n: int) -> list[int]:
    """Which songs of a set get a quick link before them (0-based): every third song."""
    return [i for i in range(3, n, 3)]


def set_prompt(kind: str, name: str, day: str, time_spoken: str | None, prev: dict | None, tracks: list[dict],
               links: list[int], intro_words: int, link_words: list[int], facts: list[str | None],
               notes: dict[str, list[str]], seg: dict, friend: str | None, recent: list[str],
               liked: list[str] | None = None, dialogue: bool = False) -> str:
    """What the model is told to write a set's talk: the break before it, and its links."""
    out = [f"Listener's first name: {name}."]
    if day or time_spoken:
        out.append(f"When: {day}" + (f", {time_spoken}" if time_spoken else "") + ". (If you give the time, say it like that.)")
    if prev:
        out.append(f"Just played: {_song(prev)}" + (f", from {speakable_title(prev.get('album') or '')}" if prev.get("album") else "") + ".")
    out.append(f"This set: {seg['brief']}" + (f" {seg['why']}" if seg.get("why") else ""))
    out.append("Songs in this set:")
    for i, t in enumerate(tracks):
        line = f"{i + 1}. {_song(t)}, from {speakable_title(t.get('album') or '')}" + (f" ({t['year']})" if t.get("year") else "") + "."
        if facts[i]:
            line += f" {facts[i]}"
        out.append(line)
    artists = []
    for t in tracks:
        a = t.get("albumArtist") or t["artist"]
        if a in notes and a not in artists:
            artists.append(a)
    for a in artists:
        out.append(f"About {a} (use at most one, only if it fits): " + " ".join(notes[a]))
    if friend:
        out.append(f"From Friend activity (a shout-out is welcome, not required): {friend}")
    if liked:
        out.append("Lines this listener gave a thumbs up (their taste in style; don't copy them): " + " | ".join(liked))
    if recent:
        # Only the openings: small models copy whole lines they're shown.
        openers = sorted({" ".join(x.split()[:2]).rstrip(",.!") for x in recent if x.split()})
        out.append("Don't start any line with: " + "; ".join(f'"{o}"' for o in openers) + ".")
    intro_task = ("the very start of the show: say hello and introduce the station, then set up the set and name song 1"
                  if kind == "open" else
                  "answering the listener's request (given above): say you've got it, warmly and briefly, then name song 1"
                  if kind == "request" else
                  "a short break after a jingle (the show is already on air: no welcome or hello): back-announce the "
                  "song that just played, then set up this set and name song 1")
    keys = ", ".join(f'"{i + 1}": "..."' for i in links)
    if dialogue:
        want = ['Write JSON: {"intro": [{"host": "A", "line": "..."}, {"host": "B", "line": "..."}, ...], "links": {' + keys + '}}.',
                f'"intro" is spoken before song 1 by two hosts, A (the main host) and B (the co-host, a friend with '
                f"opinions): a quick, natural back-and-forth of two to four short turns, {intro_task}. A names song 1 "
                f"in the last turn. At most {intro_words + 12} words in all. Links are A alone."]
    else:
        want = ['Write JSON: {"intro": "...", "links": {' + keys + '}}.',
                f'"intro" is spoken before song 1: {intro_task}. At most {intro_words} words. You may tease a later song.']
    for i, w in zip(links, link_words):
        want.append(f'"links" "{i + 1}": spoken right after song {i} ({_song(tracks[i - 1])}) finishes and before song {i + 1} '
                    f"({_song(tracks[i])}) starts: react to {speakable_title(tracks[i - 1]['title'])} in a few words, then "
                    f"introduce {speakable_title(tracks[i]['title'])}. At most {w} words.")
    if not links:
        want.append('"links" is empty: {}.')
    want.append("Keep each within its word budget: the host finishes as the singing starts.")
    return "\n".join(out + [""] + want)


def parse_dialogue(text: str | None) -> list[tuple[str, str]] | None:
    """The two hosts' turns from the model's JSON ("intro": [{"host", "line"}...]), or None."""
    data = _json(text)
    turns = data.get("intro") if isinstance(data, dict) else None
    if not isinstance(turns, list):
        return None
    out = []
    for t in turns:
        if isinstance(t, dict) and isinstance(t.get("line"), str):
            line = clean(t["line"])
            if line:
                out.append(("B" if str(t.get("host", "A")).upper().startswith("B") else "A", line))
    return out if len(out) >= 2 else None


def parse_set(text: str | None, links: list[int]) -> tuple[str | None, dict[int, str]]:
    """The intro and links (by 0-based song) from the model's JSON; anything missing is None.
    Small models vary the shape: keys in any case, "song 4" for "4", or the links as a list."""
    data = _json(text)
    if not isinstance(data, dict):
        if text and not text.lstrip().startswith(("{", "[")):
            return clean(text), {}
        if text:
            log.warning("The DJ's writer answered in a way Shelf couldn't read: %s", text[:300].replace("\n", " "))
        return None, {}
    data = {str(k).strip().lower(): v for k, v in data.items()}
    intro = data.get("intro") or data.get("break") or data.get("opening")
    intro = clean(str(intro)) if isinstance(intro, str) and intro.strip() else None
    got = data.get("links") or data.get("link") or {}
    out: dict[int, str] = {}
    if isinstance(got, list):
        got = {str(i + 1): v for i, v in zip(links, got)}
    if isinstance(got, dict):
        by_num = {}
        for k, v in got.items():
            m = re.search(r"\d+", str(k))
            if m and isinstance(v, str):
                by_num[int(m.group(0))] = v
        for i in links:
            c = clean(by_num.get(i + 1, ""))
            if c:
                out[i] = c
    if intro is None:
        log.warning("The DJ's writer left out the intro: %s", (text or "")[:300].replace("\n", " "))
    return intro, out


def fit(text: str, words: int) -> str:
    """A line cut down to about its word budget (small models run long), in whole sentences,
    always keeping the last one, which is where the next song gets named."""
    sentences = re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", text.strip())
    sentences = [x.strip() for x in sentences if x.strip()]
    if len(text.split()) <= words * 1.25 or len(sentences) < 2:
        return text
    last = sentences[-1]
    kept, n = [], len(last.split())
    for x in sentences[:-1]:
        if n + len(x.split()) > words * 1.2:
            break
        kept.append(x)
        n += len(x.split())
    return " ".join(kept + [last])


def ensure_named(text: str, t: dict) -> str:
    """Make sure a line names the song it introduces (small models sometimes forget)."""
    from .videos import fold
    title = speakable_title(t["title"])
    if fold(title) and fold(title) in fold(text):
        return text
    return f"{text.rstrip()} Here's {_song(t)}."


def set_schema(links: list[int], dialogue: bool = False) -> dict:
    """The exact shape of a set's talk, so a small model can't wander off it."""
    line = {"type": "string", "minLength": 8, "maxLength": 400}
    intro = ({"type": "array", "minItems": 2, "maxItems": 6,
              "items": {"type": "object", "properties": {"host": {"enum": ["A", "B"]}, "line": line},
                        "required": ["host", "line"]}} if dialogue else line)
    keys = [str(i + 1) for i in links]
    return {"type": "object",
            "properties": {"intro": intro,
                           "links": {"type": "object", "properties": {k: line for k in keys}, "required": keys}},
            "required": ["intro", "links"]}


# Claims a host shouldn't make unless the facts say so.
_RISKY = re.compile(r"\b(latest|newest|new album|debut|number one|no\. ?1|chart|grammy|award|platinum|sold|"
                    r"million|billion|biggest|first ever|last ever|final album|reunion|died|passed away)\b", re.I)
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
_YEAR_WORDS = re.compile(r"\b(nineteen|two thousand|twenty) [a-z -]+\b", re.I)


def checked(text: str | None, facts: str) -> str | None:
    """The line, unless it states something the facts don't back up (a year, "latest album",
    chart talk...): then None, and a safe line is used instead."""
    if not text:
        return None
    f = facts.lower()
    for y in _YEAR.findall(text):
        if y not in facts:
            return None
    for m in _RISKY.finditer(text):
        if m.group(0).lower() not in f:
            return None
    return text


NOTES_SYSTEM = ("You help a radio DJ. From the text given, and nothing else, write short facts a host could mention "
                "on air. Plain spoken English, each under 16 words, no dates as digits.")


def notes_prompt(artist: str, extract: str) -> str:
    return (f'Text about {artist}:\n{extract[:1200]}\n\nWrite JSON: {{"facts": ["...", "...", "..."]}} '
            "with two or three facts a host could drop in between songs.")


def parse_notes(text: str | None) -> list[str] | None:
    data = _json(text)
    facts = data.get("facts") if isinstance(data, dict) else data if isinstance(data, list) else None
    if not isinstance(facts, list):
        return None
    out = [clean(str(f)) for f in facts if isinstance(f, (str, int))]
    return [f for f in out if f][:3] or None


def first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    m = re.match(r"(.{20,240}?[.!?])(\s|$)", text.strip())
    return m.group(1) if m else text.strip()[:200]



# ---------- the natural voice (Chatterbox, on the graphics card) ----------

class Chatterbox:
    """Chatterbox in its own Python environment, kept loaded on the graphics card while the DJ
    talks and stopped after ten idle minutes to give the graphics memory back. Only used where
    there's a graphics card it can run on; elsewhere Kokoro speaks."""

    IDLE = 600

    def __init__(self, root: Path):
        self.root = root
        self.state: dict = {"installing": False, "step": "", "error": None}
        self._proc: subprocess.Popen | None = None
        self._device: str | None = None
        self._last = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._idle_loop, name="shelf-chatterbox-idle", daemon=True).start()

    @property
    def python(self) -> Path:
        return self.root / "venv" / "bin" / "python"

    @property
    def installed(self) -> bool:
        return self.python.exists() and (self.root / "installed").exists()

    def usable(self) -> bool:
        return self.installed and self._device != "cpu"

    def info(self) -> dict:
        return {"installed": self.installed, "device": self._device, **self.state}

    def install(self) -> None:
        """Set up Chatterbox (about 3 GB, with the graphics libraries) in the background."""
        if self.state["installing"]:
            return
        self.state.update(installing=True, step="Starting", error=None)
        threading.Thread(target=self._install, name="shelf-chatterbox-install", daemon=True).start()

    def _install(self) -> None:
        import shutil
        try:
            uv = shutil.which("uv")
            if not uv:
                raise OSError("Shelf needs uv to set this up (it's what runs Shelf)")
            self.root.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "UV_LINK_MODE": "copy", "VIRTUAL_ENV": str(self.root / "venv")}
            self.state["step"] = "Making a Python environment"
            subprocess.run([uv, "venv", "--python", "3.12", str(self.root / "venv")], check=True, capture_output=True, env=env, timeout=600)
            self.state["step"] = "Downloading Chatterbox and the graphics libraries (about 3 GB)"
            # (setuptools before 81: Chatterbox's watermarking still uses pkg_resources)
            subprocess.run([uv, "pip", "install", "--python", str(self.python), "chatterbox-tts", "setuptools<81"],
                           check=True, capture_output=True, env=env, timeout=3600)
            self.state["step"] = "Downloading the voice model"
            out = subprocess.run([str(self.python), "-c", "from chatterbox.tts import ChatterboxTTS as C; import torch; "
                                  "C.from_pretrained(device='cuda' if torch.cuda.is_available() else 'cpu'); "
                                  "print('cuda' if torch.cuda.is_available() else 'cpu')"],
                                 check=True, capture_output=True, text=True, timeout=3600)
            (self.root / "installed").write_text(out.stdout.strip().splitlines()[-1])
            self._device = out.stdout.strip().splitlines()[-1]
            self.state["step"] = "Ready" if self._device == "cuda" else "Installed, but there's no graphics card it can use here"
        except (OSError, subprocess.SubprocessError) as e:
            err = getattr(e, "stderr", None)
            self.state.update(error=f"Setting up the natural voice failed: {(err or str(e))[-300:] if isinstance(err, str) else e}")
        finally:
            self.state["installing"] = False

    def _start(self) -> None:
        worker = Path(__file__).with_name("chatterbox_worker.py")
        self._proc = subprocess.Popen([str(self.python), str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, bufsize=1)
        line = ""
        while not line.startswith("{"):  # libraries may print other things first
            line = self._proc.stdout.readline()
            if not line:
                raise OSError("The natural voice didn't start")
        ready = json.loads(line)
        self._device = ready.get("device")
        if self._device != "cuda":
            self.stop()
            raise OSError("No graphics card for the natural voice here")

    def speak(self, text: str, ref: Path | None, exaggeration: float, out: Path) -> float:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._start()
            self._last = time.monotonic()
            self._proc.stdin.write(json.dumps({"text": text, "ref": str(ref) if ref else None, "exaggeration": exaggeration,
                                               "cfg": 0.4, "out": str(out)}) + "\n")
            self._proc.stdin.flush()
            res = json.loads(self._proc.stdout.readline() or "{}")
            self._last = time.monotonic()
        if not res.get("ok"):
            raise OSError(res.get("error") or "The natural voice failed")
        return res["seconds"]

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None

    def _idle_loop(self) -> None:
        while True:
            time.sleep(30)
            if self._proc and time.monotonic() - self._last > self.IDLE and not self._lock.locked():
                log.info("Stopping the natural voice (idle)")
                self.stop()
