"""The DJ's voice: a long-running helper that speaks lines with Kokoro.

It runs in its own Python environment (Kokoro's libraries don't support Shelf's Python yet),
keeps the voice model loaded, and takes one request per line on stdin:
    {"text": "...", "voice": "am_michael", "speed": 1.0, "out": "/path/line.wav"}
or, to speak a line in pieces with their own pace and the pause after each:
    {"chunks": [{"text": "...", "speed": 1.04, "pause": 0.3}, ...], "voice": ..., "out": ...}
answering each with one line of JSON on stdout: {"ok": true, "seconds": 4.2} or {"ok": false, "error": "..."}.

Standalone on purpose: it doesn't import Shelf. Usage:
    <tts venv>/bin/python tts_worker.py <model.onnx> <voices.bin>
"""

import json
import sys


def main() -> None:
    import soundfile as sf
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(sys.argv[1], sys.argv[2])
    voices = set(kokoro.get_voices()) if hasattr(kokoro, "get_voices") else set()
    print(json.dumps({"ready": True, "voices": sorted(voices)}), flush=True)
    for line in sys.stdin:
        try:
            req = json.loads(line)
            import numpy as np
            voice = req.get("voice") or "am_michael"
            lang = "en-gb" if voice[:1] == "b" else "en-us"
            chunks = req.get("chunks") or [{"text": req["text"], "speed": req.get("speed") or 1.0, "pause": 0}]
            parts, rate = [], 24000
            for c in chunks:
                samples, rate = kokoro.create(c["text"], voice=voice, speed=float(c.get("speed") or 1.0), lang=lang)
                parts.append(samples)
                if c.get("pause"):
                    parts.append(np.zeros(int(rate * float(c["pause"])), dtype=samples.dtype))
            samples = np.concatenate(parts)
            sf.write(req["out"], samples, rate)
            print(json.dumps({"ok": True, "seconds": round(len(samples) / rate, 2)}), flush=True)
        except Exception as e:  # report and carry on with the next line
            print(json.dumps({"ok": False, "error": str(e)}), flush=True)


if __name__ == "__main__":
    main()
